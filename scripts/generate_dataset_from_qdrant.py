"""
Generate Fine-Tuning Dataset from Qdrant Collections.

Extracts documents from ALL Qdrant collections to create a comprehensive
training dataset for fine-tuning embeddings, reranker, and LoRA.

This is an improvement over generate_lora_dataset.py that reads from the
vector database instead of local PDFs, allowing training on SharePoint-synced docs.

Usage:
    python scripts/generate_dataset_from_qdrant.py --limit 100
"""

import os
import json
import argparse
import random
import sys
from typing import List, Dict, Any, Optional
from datetime import datetime

import requests

# Configuration
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.getenv("LLM_MODEL", "llama3.1:8b-instruct-q8_0")
OUTPUT_DIR = "data"

# All collections to extract from (customize per deployment)
COLLECTIONS = ["documents", "webs"]

# Prompts for dataset generation
QA_GENERATION_PROMPT = """Eres un experto creando datos de entrenamiento para sistemas RAG empresariales.
Dado un fragmento de texto de un documento, genera 2 ejemplos de entrenamiento en formato JSON.

Cada ejemplo debe tener:
- "question": Una pregunta clara y específica sobre el contenido (en español)
- "context": El contexto relevante del documento (puedes resumirlo si es largo)
- "answer": La respuesta completa basada en el contexto, citando la fuente

Las preguntas deben ser:
1. Una pregunta factual directa
2. Una pregunta que requiera explicar o resumir

Responde SOLO con JSON válido, sin texto adicional:
[
  {"question": "...", "context": "...", "answer": "..."},
  {"question": "...", "context": "...", "answer": "..."}
]"""


def get_collection_stats() -> Dict[str, int]:
    """Get point counts for all collections."""
    stats = {}
    for col in COLLECTIONS:
        try:
            r = requests.get(f"{QDRANT_URL}/collections/{col}", timeout=10)
            if r.status_code == 200:
                data = r.json()
                stats[col] = data.get("result", {}).get("points_count", 0)
            else:
                stats[col] = 0
        except Exception as e:
            print(f"[!] Error getting stats for {col}: {e}")
            stats[col] = 0
    return stats


def sample_documents_from_collection(
    collection: str, 
    limit: int,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Sample documents from a Qdrant collection."""
    documents = []
    
    try:
        # Use scroll to get documents with payloads
        payload = {
            "limit": limit,
            "offset": offset,
            "with_payload": True,
            "with_vector": False
        }
        
        r = requests.post(
            f"{QDRANT_URL}/collections/{collection}/points/scroll",
            json=payload,
            timeout=30
        )
        
        if r.status_code == 200:
            data = r.json()
            points = data.get("result", {}).get("points", [])
            
            for point in points:
                payload = point.get("payload", {})
                if payload.get("text"):
                    documents.append({
                        "text": payload.get("text", ""),
                        "filename": payload.get("filename", "unknown"),
                        "page": payload.get("page"),
                        "collection": collection,
                        "from_ocr": payload.get("from_ocr", False)
                    })
        else:
            print(f"[!] Error scrolling {collection}: {r.status_code}")
            
    except Exception as e:
        print(f"[!] Error sampling from {collection}: {e}")
    
    return documents


def generate_qa_pairs(doc: Dict[str, Any], model: str = MODEL) -> List[Dict[str, Any]]:
    """Generate Q&A pairs from a document using LLM."""
    
    text = doc["text"][:2500]  # Limit context size
    filename = doc["filename"]
    page = doc.get("page", "N/A")
    collection = doc["collection"]
    
    prompt = f"""Documento: {filename} (Página {page}, Colección: {collection})

Texto:
{text}

Genera 2 ejemplos de entrenamiento en formato JSON:"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": QA_GENERATION_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "format": "json"
            },
            timeout=180
        )
        
        if response.status_code != 200:
            print(f"  [!] Ollama error: {response.status_code}")
            return []
        
        data = response.json()
        content = data.get("message", {}).get("content", "")
        
        # Parse JSON response
        parsed = json.loads(content)
        
        if isinstance(parsed, list):
            examples = parsed
        elif isinstance(parsed, dict) and "examples" in parsed:
            examples = parsed["examples"]
        else:
            examples = [parsed] if "question" in parsed else []
        
        # Add metadata to each example
        for ex in examples:
            ex["source_file"] = filename
            ex["page"] = page
            ex["collection"] = collection
            
            # Ensure answer includes source citation
            if "answer" in ex and not ex["answer"].endswith("]"):
                ex["answer"] += f"\n\n[Fuente: {filename}, página {page}]"
        
        return examples
        
    except json.JSONDecodeError as e:
        print(f"  [!] JSON parse error: {e}")
        return []
    except Exception as e:
        print(f"  [!] Error generating QA: {e}")
        return []


def convert_to_training_formats(examples: List[Dict]) -> Dict[str, List]:
    """Convert examples to different training formats."""
    
    # Format 1: For embedding fine-tuning (question, context pairs)
    embedding_pairs = []
    for ex in examples:
        if ex.get("question") and ex.get("context"):
            embedding_pairs.append({
                "text1": ex["question"],
                "text2": ex["context"],
                "label": 1.0
            })
    
    # Format 2: Alpaca format for LoRA
    alpaca_examples = []
    for ex in examples:
        alpaca_examples.append({
            "instruction": ex.get("question", ""),
            "input": ex.get("context", ""),
            "output": ex.get("answer", ""),
            "source_file": ex.get("source_file", ""),
            "collection": ex.get("collection", "")
        })
    
    # Format 3: ShareGPT format for conversational fine-tuning
    sharegpt_examples = []
    system_prompt = """Eres un asistente RAG inteligente.
Responde basándote ÚNICAMENTE en el contexto proporcionado.
Cita siempre las fuentes al final de tu respuesta.
Responde siempre en español de forma profesional."""

    for ex in examples:
        sharegpt_examples.append({
            "conversations": [
                {"from": "system", "value": system_prompt},
                {"from": "human", "value": f"{ex.get('question', '')}\n\nContexto:\n{ex.get('context', '')}"},
                {"from": "gpt", "value": ex.get("answer", "")}
            ],
            "source_file": ex.get("source_file", ""),
            "collection": ex.get("collection", "")
        })
    
    return {
        "embedding_pairs": embedding_pairs,
        "alpaca": alpaca_examples,
        "sharegpt": sharegpt_examples,
        "raw": examples
    }


def main():
    parser = argparse.ArgumentParser(description="Generate fine-tuning dataset from Qdrant")
    parser.add_argument("--limit", "-l", type=int, default=50,
                       help="Total examples to generate per collection")
    parser.add_argument("--output", "-o", type=str, default="data/finetune_dataset.json",
                       help="Output JSON file")
    parser.add_argument("--model", "-m", type=str, default=MODEL,
                       help="Ollama model for generation")
    parser.add_argument("--dry-run", action="store_true",
                       help="Only show stats, don't generate")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  QDRANT -> FINE-TUNING DATASET GENERATOR")
    print("=" * 60)
    print()
    
    # Get collection stats
    print("[*] Checking Qdrant collections...")
    stats = get_collection_stats()
    total_points = sum(stats.values())
    
    print(f"[*] Found {len(stats)} collections with {total_points:,} total points:")
    for col, count in stats.items():
        print(f"    - {col}: {count:,} points")
    print()
    
    if args.dry_run:
        print("[*] Dry run - exiting without generation")
        return
    
    # Calculate samples per collection (proportional to size)
    samples_per_collection = {}
    for col, count in stats.items():
        if count > 0:
            # Proportional sampling, minimum 5 if collection has data
            proportion = count / total_points
            samples = max(5, int(args.limit * proportion))
            samples_per_collection[col] = min(samples, count)
    
    print(f"[*] Sampling plan (total limit: {args.limit}):")
    for col, samples in samples_per_collection.items():
        print(f"    - {col}: {samples} documents")
    print()
    
    # Sample and generate
    all_examples = []
    
    for collection, sample_count in samples_per_collection.items():
        print(f"[*] Processing: {collection}")
        
        # Sample documents
        docs = sample_documents_from_collection(collection, sample_count)
        print(f"  -> Sampled {len(docs)} documents")
        
        # Shuffle and limit
        random.shuffle(docs)
        
        for i, doc in enumerate(docs[:sample_count]):
            if len(doc["text"].strip()) < 200:
                continue
            
            print(f"  -> Generating QA for {doc['filename']} (page {doc.get('page', 'N/A')})...")
            examples = generate_qa_pairs(doc, args.model)
            
            if examples:
                all_examples.extend(examples)
                print(f"    [OK] Generated {len(examples)} examples")
    
    print()
    print(f"[*] Total examples generated: {len(all_examples)}")
    
    # Convert to training formats
    formatted = convert_to_training_formats(all_examples)
    
    # Save outputs
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    
    # Main output with all formats
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(formatted, f, indent=2, ensure_ascii=False)
    
    # Individual format files
    base = args.output.replace(".json", "")
    
    with open(f"{base}_embeddings.json", "w", encoding="utf-8") as f:
        json.dump(formatted["embedding_pairs"], f, indent=2, ensure_ascii=False)
    
    with open(f"{base}_alpaca.json", "w", encoding="utf-8") as f:
        json.dump(formatted["alpaca"], f, indent=2, ensure_ascii=False)
    
    with open(f"{base}_sharegpt.json", "w", encoding="utf-8") as f:
        json.dump(formatted["sharegpt"], f, indent=2, ensure_ascii=False)
    
    print()
    print("=" * 60)
    print(f"[+] Dataset saved to: {args.output}")
    print(f"[+] Embedding pairs: {base}_embeddings.json ({len(formatted['embedding_pairs'])} pairs)")
    print(f"[+] Alpaca format: {base}_alpaca.json ({len(formatted['alpaca'])} examples)")
    print(f"[+] ShareGPT format: {base}_sharegpt.json ({len(formatted['sharegpt'])} examples)")
    print("=" * 60)
    
    # Summary by collection
    print()
    print("[*] Examples by collection:")
    collection_counts = {}
    for ex in all_examples:
        col = ex.get("collection", "unknown")
        collection_counts[col] = collection_counts.get(col, 0) + 1
    
    for col, count in sorted(collection_counts.items()):
        print(f"    - {col}: {count} examples")


if __name__ == "__main__":
    main()

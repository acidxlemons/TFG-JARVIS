"""
Generate LoRA Fine-Tuning Dataset for RAG.

Creates instruction-tuning dataset from indexed documents for training
a language model to better answer questions based on document context.

Formats:
- Alpaca format (instruction, input, output)
- ShareGPT format (conversations)

Usage:
    python scripts/generate_lora_dataset.py --input data/watch --output data/lora_dataset.json
"""

import os
import json
import argparse
import random
import sys
from pathlib import Path
from typing import List, Dict, Any

try:
    import fitz  # PyMuPDF
except ImportError:
    print("[!] PyMuPDF not installed. Run: pip install PyMuPDF")
    sys.exit(1)

import requests

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Configuration
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b-instruct-q8_0"
OUTPUT_DIR = "data"

# System prompts for different generation types
INSTRUCTION_GEN_PROMPT = """Eres un experto creando datos de entrenamiento para modelos de lenguaje.
Dado un fragmento de texto de un documento, genera 3 ejemplos de entrenamiento en formato JSON.

Cada ejemplo debe tener:
- "instruction": Una pregunta clara sobre el contenido
- "input": El contexto del documento (puedes resumirlo)
- "output": La respuesta completa y bien formateada, citando la fuente

Las preguntas deben ser variadas:
1. Una pregunta factual directa
2. Una pregunta que requiera explicar un concepto
3. Una pregunta que pida resumir o comparar

Responde SOLO con JSON válido, sin texto adicional:
[
  {"instruction": "...", "input": "...", "output": "..."},
  {"instruction": "...", "input": "...", "output": "..."},
  {"instruction": "...", "input": "...", "output": "..."}
]"""

RAG_STYLE_PROMPT = """Eres un asistente RAG empresarial. Cuando respondas:
1. Basa tu respuesta ÚNICAMENTE en el contexto proporcionado
2. Cita las fuentes al final: [Fuente: nombre_documento, página X]
3. Si no hay información suficiente, indícalo claramente
4. Usa un tono profesional y estructurado
5. Responde siempre en español"""


def extract_text_from_pdf(filepath: str) -> List[Dict[str, Any]]:
    """Extract text from PDF with page information."""
    pages = []
    try:
        doc = fitz.open(filepath)
        for page_num, page in enumerate(doc, 1):
            text = page.get_text()
            if text.strip():
                pages.append({
                    "text": text,
                    "page": page_num,
                    "filename": Path(filepath).name
                })
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    return pages


def generate_examples(chunk: Dict[str, Any], model: str = MODEL) -> List[Dict[str, Any]]:
    """Generate training examples from a text chunk using LLM."""
    
    prompt = f"""Documento: {chunk['filename']} (Página {chunk['page']})

Texto:
{chunk['text'][:2000]}

Genera 3 ejemplos de entrenamiento en formato JSON:"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": INSTRUCTION_GEN_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "format": "json"
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=180)
        response.raise_for_status()
        data = response.json()
        content = data['message']['content']
        
        # Parse JSON response
        parsed = json.loads(content)
        
        if isinstance(parsed, list):
            examples = parsed
        elif isinstance(parsed, dict) and 'examples' in parsed:
            examples = parsed['examples']
        else:
            examples = [parsed] if 'instruction' in parsed else []
        
        # Add metadata to each example
        for ex in examples:
            ex['source_file'] = chunk['filename']
            ex['page'] = chunk['page']
            
            # Add RAG-style formatting to outputs
            if 'output' in ex and not ex['output'].endswith(']'):
                ex['output'] += f"\n\n[Fuente: {chunk['filename']}, página {chunk['page']}]"
        
        return examples
        
    except json.JSONDecodeError as e:
        print(f"  [!] JSON parse error: {e}")
        return []
    except Exception as e:
        print(f"  [!] Error generating examples: {e}")
        return []


def generate_conversation_examples(examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert Alpaca format to ShareGPT conversation format."""
    conversations = []
    
    for ex in examples:
        conv = {
            "conversations": [
                {"from": "system", "value": RAG_STYLE_PROMPT},
                {"from": "human", "value": f"{ex['instruction']}\n\nContexto:\n{ex.get('input', '')}"},
                {"from": "gpt", "value": ex['output']}
            ],
            "source_file": ex.get('source_file', ''),
            "page": ex.get('page', 0)
        }
        conversations.append(conv)
    
    return conversations


def create_multi_turn_examples(examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create multi-turn conversation examples for better instruction following."""
    multi_turn = []
    
    # Group examples by source file
    by_file = {}
    for ex in examples:
        fname = ex.get('source_file', 'unknown')
        if fname not in by_file:
            by_file[fname] = []
        by_file[fname].append(ex)
    
    # Create follow-up conversations
    for fname, file_examples in by_file.items():
        if len(file_examples) >= 2:
            # Take pairs for multi-turn
            for i in range(0, len(file_examples) - 1, 2):
                ex1, ex2 = file_examples[i], file_examples[i + 1]
                
                multi = {
                    "conversations": [
                        {"from": "system", "value": RAG_STYLE_PROMPT},
                        {"from": "human", "value": ex1['instruction'] + f"\n\nContexto:\n{ex1.get('input', '')}"},
                        {"from": "gpt", "value": ex1['output']},
                        {"from": "human", "value": f"Y además, {ex2['instruction'].lower()}"},
                        {"from": "gpt", "value": ex2['output']}
                    ],
                    "source_file": fname,
                    "is_multi_turn": True
                }
                multi_turn.append(multi)
    
    return multi_turn


def main():
    parser = argparse.ArgumentParser(description="Generate LoRA fine-tuning dataset")
    parser.add_argument("--input", "-i", type=str, default="data/watch", 
                       help="Input directory with documents")
    parser.add_argument("--output", "-o", type=str, default="data/lora_dataset.json",
                       help="Output JSON file")
    parser.add_argument("--limit", "-l", type=int, default=10,
                       help="Max number of files to process")
    parser.add_argument("--pages-per-file", "-p", type=int, default=5,
                       help="Max pages to process per file")
    parser.add_argument("--format", "-f", type=str, default="both",
                       choices=["alpaca", "sharegpt", "both"],
                       help="Output format")
    parser.add_argument("--model", "-m", type=str, default=MODEL,
                       help="Ollama model for generation")
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    
    # Find PDF files
    if input_path.is_file():
        files = [input_path]
    else:
        files = list(input_path.glob("**/*.pdf"))
    
    if not files:
        print(f"[X] No PDF files found in {args.input}")
        sys.exit(1)
    
    print(f"[*] Found {len(files)} PDF files")
    print(f"[*] Processing max {args.limit} files, {args.pages_per_file} pages each")
    print(f"[*] Using model: {args.model}")
    print()
    
    all_examples = []
    
    for filepath in files[:args.limit]:
        print(f"[*] Processing: {filepath.name}")
        
        pages = extract_text_from_pdf(str(filepath))
        
        if not pages:
            print(f"  [!] No text extracted")
            continue
        
        # Sample pages if too many
        if len(pages) > args.pages_per_file:
            # Take first, last, and random middle pages
            selected = [pages[0], pages[-1]]
            middle = pages[1:-1]
            if middle:
                selected.extend(random.sample(middle, min(args.pages_per_file - 2, len(middle))))
            pages = selected
        
        for page in pages:
            if len(page['text'].strip()) < 200:
                continue
                
            print(f"  → Generating examples for page {page['page']}...")
            examples = generate_examples(page, args.model)
            
            if examples:
                all_examples.extend(examples)
                print(f"    ✓ Generated {len(examples)} examples")
    
    print()
    print(f"[*] Total Alpaca examples: {len(all_examples)}")
    
    # Create output based on format
    output_data = {}
    
    if args.format in ["alpaca", "both"]:
        output_data["alpaca"] = all_examples
        print(f"[*] Alpaca format: {len(all_examples)} examples")
    
    if args.format in ["sharegpt", "both"]:
        sharegpt = generate_conversation_examples(all_examples)
        multi_turn = create_multi_turn_examples(all_examples)
        output_data["sharegpt"] = sharegpt + multi_turn
        print(f"[*] ShareGPT format: {len(sharegpt)} single-turn + {len(multi_turn)} multi-turn")
    
    # Save
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print()
    print("=" * 50)
    print(f"[+] Dataset saved to: {args.output}")
    print("=" * 50)
    
    # Also save individual format files for convenience
    if args.format == "both":
        base = Path(args.output).stem
        parent = Path(args.output).parent
        
        with open(parent / f"{base}_alpaca.json", "w", encoding="utf-8") as f:
            json.dump(all_examples, f, indent=2, ensure_ascii=False)
        
        with open(parent / f"{base}_sharegpt.json", "w", encoding="utf-8") as f:
            json.dump(output_data["sharegpt"], f, indent=2, ensure_ascii=False)
        
        print(f"[+] Also saved: {base}_alpaca.json and {base}_sharegpt.json")


if __name__ == "__main__":
    main()

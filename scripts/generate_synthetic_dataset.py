
"""
Script to generate synthetic "Golden Dataset" for RAG evaluation.
Iterates over documents in `data/`, chunks them, and uses Ollama to generate Q&A pairs.

Usage:
    python scripts/generate_synthetic_dataset.py --input data/ --limit 10
"""

import os
import json
import argparse
import fitz  # PyMuPDF
import requests
import sys
from pathlib import Path

# Add backend to path to import SmartChunker
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app.processing.chunking.smart_chunker import SmartChunker

# Configuration
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b-instruct-q8_0"  # Using Q8 for better quality
OUTPUT_FILE = "tests/data/synthetic_gold_dataset.json"

SYSTEM_PROMPT = """You are an expert at creating high-quality exam questions for a semantic search and RAG system evaluation.
Given a text chunk, your goal is to generate 2 distinct, complex questions that can be answered ONLY using the information in that chunk.
For each question, provide the exact answer found in the text.

Output valid JSON only, with this structure:
[
  {
    "question": "The question here?",
    "answer": "The specific answer here."
  },
  {
    "question": "Another question?",
    "answer": "Another answer."
  }
]
"""

def extract_text_from_pdf(filepath):
    """Extracts text from a PDF file using PyMuPDF."""
    text = ""
    try:
        doc = fitz.open(filepath)
        for page in doc:
            text += f"=== PÁGINA ===\n{page.get_text()}\n"
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    return text

def generate_qa(chunk_text):
    """Calls Ollama to generate Q&A pairs for a text chunk."""
    prompt = f"Context:\n{chunk_text}\n\nGenerate Q&A JSON:"
    
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "format": "json"
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()
        content = data['message']['content']
        parsed = json.loads(content)
        
        # Handle different response structures
        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict):
            # Some models wrap in an object like {"questions": [...]}
            if 'questions' in parsed:
                return parsed['questions']
            elif 'question' in parsed and 'answer' in parsed:
                return [parsed]  # Single Q&A wrapped as dict
            else:
                # Try to extract any list value
                for v in parsed.values():
                    if isinstance(v, list):
                        return v
        return []
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON from LLM: {e}")
        return []
    except Exception as e:
        print(f"Error calling Ollama: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic Q&A dataset.")
    parser.add_argument("--input", "-i", type=str, default="data/", help="Input directory or file")
    parser.add_argument("--limit", "-l", type=int, default=5, help="Max number of files to process")
    parser.add_argument("--chunks-per-file", "-c", type=int, default=3, help="Max chunks to process per file")
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    files = []
    
    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        files = list(input_path.glob("*.pdf"))
    
    print(f"Found {len(files)} files. Processing max {args.limit}...")
    
    chunker = SmartChunker(chunk_size=600, overlap=50)
    dataset = []
    
    count = 0
    for filepath in files[:args.limit]:
        print(f"Processing {filepath.name}...")
        text = extract_text_from_pdf(str(filepath))
        if not text:
            continue
            
        chunks = chunker.chunk_text(text, filepath.name)
        
        # Process a few chunks per file to save time
        for chunk in chunks[:args.chunks_per_file]:
            if len(chunk['text']) < 200: # Skip small chunks
                continue
                
            qa_pairs = generate_qa(chunk['text'])
            
            for item in qa_pairs:
                dataset.append({
                    "question": item['question'],
                    "answer": item['answer'],
                    "context": chunk['text'],
                    "source_file": filepath.name,
                    "page": chunk['metadata'].get('page')
                })
                print(f"  + Generated Q: {item['question']}")
        
        count += 1
        
    # Save dataset
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)
        
    print(f"\nSaved {len(dataset)} examples to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()

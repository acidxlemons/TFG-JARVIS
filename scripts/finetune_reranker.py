"""
Fine-Tune Cross-Encoder Reranker for Domain-Specific RAG.

Cross-encoders are more accurate than bi-encoders for reranking because
they see both query and document together. This script fine-tunes a
cross-encoder to improve the ranking of retrieved documents.

Usage:
    python scripts/finetune_reranker.py --epochs 3
"""

import os
import json
import argparse
import sys
import random
from pathlib import Path
from typing import List, Tuple

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from sentence_transformers import CrossEncoder, InputExample
    from sentence_transformers.cross_encoder.evaluation import CEBinaryClassificationEvaluator
    CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CROSS_ENCODER_AVAILABLE = False
    print("[!] sentence-transformers not installed correctly")
    print("    Run: pip install sentence-transformers")

# Configuration
BASE_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"  # Good multilingual base
OUTPUT_DIR = "models/finetuned_reranker"
DATASET_PATH = "tests/data/synthetic_gold_dataset.json"


def load_training_data(path: str) -> List[InputExample]:
    """
    Load Q&A dataset and create training examples for cross-encoder.
    Creates positive pairs (question, context) and negative pairs.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    all_contexts = [item.get("context", "") for item in data if item.get("context")]
    
    examples = []
    for item in data:
        question = item["question"]
        context = item.get("context", "")
        
        if not question or not context:
            continue
        
        # Positive pair: question matches its context (label = 1)
        examples.append(InputExample(
            texts=[question, context],
            label=1.0
        ))
        
        # Hard negative: random different context (label = 0)
        wrong_context = random.choice([c for c in all_contexts if c != context])
        examples.append(InputExample(
            texts=[question, wrong_context],
            label=0.0
        ))
    
    print(f"[*] Created {len(examples)} training examples ({len(examples)//2} positive + {len(examples)//2} negative)")
    return examples


def finetune_reranker(
    examples: List[InputExample],
    base_model: str = BASE_MODEL,
    output_dir: str = OUTPUT_DIR,
    epochs: int = 3,
    batch_size: int = 16,
    warmup_ratio: float = 0.1,
):
    """
    Fine-tune the cross-encoder reranker.
    """
    from torch.utils.data import DataLoader
    
    print(f"\n[*] Loading base model: {base_model}")
    model = CrossEncoder(base_model, num_labels=1)
    
    # Split into train/dev
    random.shuffle(examples)
    dev_size = max(10, len(examples) // 10)
    train_examples = examples[:-dev_size]
    dev_examples = examples[-dev_size:]
    
    print(f"[*] Training parameters:")
    print(f"    - Train examples: {len(train_examples)}")
    print(f"    - Dev examples: {len(dev_examples)}")
    print(f"    - Epochs: {epochs}")
    print(f"    - Batch size: {batch_size}")
    
    # Create evaluator
    evaluator = CEBinaryClassificationEvaluator.from_input_examples(
        dev_examples, 
        name="dev"
    )
    
    # Create DataLoader
    train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=batch_size)
    
    # Calculate warmup
    num_train_steps = len(train_dataloader) * epochs
    warmup_steps = int(num_train_steps * warmup_ratio)
    
    print(f"\n[*] Starting fine-tuning...")
    
    model.fit(
        train_dataloader=train_dataloader,
        evaluator=evaluator,
        epochs=epochs,
        warmup_steps=warmup_steps,
        output_path=output_dir,
        show_progress_bar=True,
    )
    
    print(f"\n[+] Reranker saved to: {output_dir}")
    return model


def main():
    parser = argparse.ArgumentParser(description="Fine-tune cross-encoder reranker")
    parser.add_argument("--epochs", "-e", type=int, default=3, help="Training epochs")
    parser.add_argument("--batch-size", "-b", type=int, default=16, help="Batch size")
    parser.add_argument("--dataset", "-d", type=str, default=DATASET_PATH)
    parser.add_argument("--output", "-o", type=str, default=OUTPUT_DIR)
    
    args = parser.parse_args()
    
    if not CROSS_ENCODER_AVAILABLE:
        print("[X] Cannot proceed without sentence-transformers")
        sys.exit(1)
    
    # Check dataset exists
    if not Path(args.dataset).exists():
        print(f"[X] Dataset not found: {args.dataset}")
        print("    Run: python scripts/generate_synthetic_dataset.py first")
        sys.exit(1)
    
    # Load and prepare data
    examples = load_training_data(args.dataset)
    
    if len(examples) < 20:
        print(f"[X] Not enough examples ({len(examples)}). Need at least 20.")
        sys.exit(1)
    
    # Fine-tune
    os.makedirs(args.output, exist_ok=True)
    model = finetune_reranker(
        examples=examples,
        output_dir=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
    )
    
    print("\n" + "="*50)
    print("[+] Reranker fine-tuning complete!")
    print("="*50)
    print(f"\nTo use the fine-tuned reranker:")
    print(f"  reranker = CrossEncoder('{args.output}')")


if __name__ == "__main__":
    main()

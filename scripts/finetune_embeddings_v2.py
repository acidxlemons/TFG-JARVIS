"""
Fine-Tune Embedding Model for Enterprise RAG System.

This script fine-tunes the sentence-transformer embedding model using
the multi-collection dataset generated from Qdrant.

Supports both the new format (text1/text2) and old format (question/context).

Usage:
    python scripts/finetune_embeddings_v2.py --epochs 3 --dataset data/finetune_dataset_embeddings.json
"""

import os
import json
import argparse
import random
import sys
from pathlib import Path
from typing import List

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from sentence_transformers import SentenceTransformer, InputExample, losses
    from torch.utils.data import DataLoader
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    InputExample = None  # Placeholder for type hints
    print("[!] sentence-transformers not installed correctly")
    print("    Run: pip install sentence-transformers")

# Configuration - INCREMENTAL TRAINING
# If a fine-tuned model exists, use it as base for continued training
# Otherwise fall back to the original base model
ORIGINAL_BASE_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
FINETUNED_MODEL_DIR = "models/finetuned_embeddings"

# Check if fine-tuned model exists and use it for incremental training
import os
if os.path.exists(FINETUNED_MODEL_DIR) and os.path.exists(os.path.join(FINETUNED_MODEL_DIR, "config.json")):
    BASE_MODEL = FINETUNED_MODEL_DIR  # Continue training from previous fine-tuned model
    print(f"[*] INCREMENTAL MODE: Training from previous fine-tuned model: {FINETUNED_MODEL_DIR}")
else:
    BASE_MODEL = ORIGINAL_BASE_MODEL  # First training - use original base
    print(f"[*] INITIAL MODE: Training from base model: {ORIGINAL_BASE_MODEL}")

OUTPUT_DIR = "models/finetuned_embeddings"
DEFAULT_DATASET = "data/finetune_dataset_embeddings.json"


def load_training_data(path: str) -> List:
    """
    Load dataset and convert to training examples.
    Supports both new format (text1/text2) and old format (question/context).
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    examples = []
    for item in data:
        # Try new format first (text1/text2)
        text1 = item.get("text1") or item.get("question", "")
        text2 = item.get("text2") or item.get("context", "")
        label = item.get("label", 1.0)
        
        if text1 and text2:
            examples.append(InputExample(
                texts=[text1, text2],
                label=float(label)
            ))
    
    print(f"[*] Loaded {len(examples)} training examples")
    return examples


def create_hard_negatives(examples: List) -> List:
    """
    Create hard negative examples by pairing questions with wrong contexts.
    """
    if len(examples) < 2:
        print("[!] Not enough examples for hard negatives")
        return []
    
    negatives = []
    all_contexts = [ex.texts[1] for ex in examples]
    
    for ex in examples:
        question = ex.texts[0]
        correct_context = ex.texts[1]
        
        # Pick a random different context as negative
        wrong_contexts = [c for c in all_contexts if c != correct_context]
        if wrong_contexts:
            wrong_context = random.choice(wrong_contexts)
            negatives.append(InputExample(
                texts=[question, wrong_context],
                label=0.0
            ))
    
    print(f"[*] Created {len(negatives)} hard negative examples")
    return negatives


def finetune_model(
    examples: List,
    base_model: str = BASE_MODEL,
    output_dir: str = OUTPUT_DIR,
    epochs: int = 3,
    batch_size: int = 8,
    warmup_ratio: float = 0.1,
    use_cpu: bool = False,
):
    """
    Fine-tune the embedding model using contrastive learning.
    """
    print(f"\n[*] Loading base model: {base_model}")
    
    # Force CPU if requested or if CUDA has issues
    device = "cpu" if use_cpu else None
    model = SentenceTransformer(base_model, device=device)
    
    # Create dataloader
    train_dataloader = DataLoader(examples, shuffle=True, batch_size=batch_size)
    
    # Use CosineSimilarityLoss
    train_loss = losses.CosineSimilarityLoss(model)
    
    # Calculate warmup steps
    warmup_steps = max(1, int(len(train_dataloader) * epochs * warmup_ratio))
    
    print(f"[*] Training parameters:")
    print(f"    - Examples: {len(examples)}")
    print(f"    - Epochs: {epochs}")
    print(f"    - Batch size: {batch_size}")
    print(f"    - Warmup steps: {warmup_steps}")
    
    # Fit the model
    print(f"\n[*] Starting fine-tuning...")
    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=epochs,
        warmup_steps=warmup_steps,
        output_path=output_dir,
        show_progress_bar=True,
    )
    
    print(f"\n[+] Model saved to: {output_dir}")
    return model


def main():
    parser = argparse.ArgumentParser(description="Fine-tune embedding model v2")
    parser.add_argument("--epochs", "-e", type=int, default=3, help="Training epochs")
    parser.add_argument("--batch-size", "-b", type=int, default=8, help="Batch size")
    parser.add_argument("--dataset", "-d", type=str, default=DEFAULT_DATASET)
    parser.add_argument("--output", "-o", type=str, default=OUTPUT_DIR)
    parser.add_argument("--model", "-m", type=str, default=BASE_MODEL, help="Base model")
    parser.add_argument("--cpu", action="store_true", help="Force CPU execution")
    
    args = parser.parse_args()
    
    if not SENTENCE_TRANSFORMERS_AVAILABLE:
        print("[X] Cannot proceed without sentence-transformers")
        sys.exit(1)
    
    # Check dataset exists
    if not Path(args.dataset).exists():
        print(f"[X] Dataset not found: {args.dataset}")
        print("    Run: python scripts/generate_dataset_from_qdrant.py first")
        sys.exit(1)
    
    print("=" * 60)
    print("  ENTERPRISE RAG EMBEDDINGS FINE-TUNING")
    print("=" * 60)
    print()
    
    # Load and prepare data
    positive_examples = load_training_data(args.dataset)
    negative_examples = create_hard_negatives(positive_examples)
    
    # Combine positive and negative examples
    all_examples = positive_examples + negative_examples
    print(f"[*] Total training examples: {len(all_examples)}")
    
    # Fine-tune
    os.makedirs(args.output, exist_ok=True)
    model = finetune_model(
        examples=all_examples,
        base_model=args.model,
        output_dir=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        use_cpu=args.cpu,
    )
    
    print("\n" + "=" * 60)
    print("[+] Fine-tuning complete!")
    print("=" * 60)
    print(f"\nTo use the fine-tuned model in RAG backend:")
    print(f"  1. Update .env: EMBEDDING_MODEL={args.output}")
    print(f"  2. Restart: docker compose restart rag-backend")
    print(f"\nOr test directly:")
    print(f"  from sentence_transformers import SentenceTransformer")
    print(f"  model = SentenceTransformer('{args.output}')")


if __name__ == "__main__":
    main()

"""
Fine-Tune Embedding Model for Domain-Specific RAG.

This script fine-tunes the sentence-transformer embedding model
using the synthetic Q&A dataset to improve retrieval accuracy.

Usage:
    python scripts/finetune_embeddings.py --epochs 3
"""

import os
import json
import argparse
import sys
from pathlib import Path
from typing import List, Tuple

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from sentence_transformers import SentenceTransformer, InputExample, losses
    from sentence_transformers.evaluation import EmbeddingSimilarityEvaluator
    from torch.utils.data import DataLoader
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    print("[!] sentence-transformers not installed correctly")
    print("    Run: pip install sentence-transformers")

# Configuration
BASE_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # Current model
OUTPUT_DIR = "models/finetuned_embeddings"
DATASET_PATH = "tests/data/synthetic_gold_dataset.json"


def load_training_data(path: str) -> List[InputExample]:
    """
    Load Q&A dataset and convert to training examples.
    Creates (question, context) positive pairs.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    examples = []
    for item in data:
        question = item["question"]
        context = item.get("context", "")
        
        if question and context:
            # Positive pair: question matches its context
            examples.append(InputExample(
                texts=[question, context],
                label=1.0  # High similarity
            ))
    
    print(f"[*] Loaded {len(examples)} training examples")
    return examples


def create_hard_negatives(examples: List[InputExample]) -> List[InputExample]:
    """
    Create hard negative examples by pairing questions with wrong contexts.
    This teaches the model what NOT to match.
    """
    import random
    
    negatives = []
    all_contexts = [ex.texts[1] for ex in examples]
    
    for ex in examples:
        question = ex.texts[0]
        correct_context = ex.texts[1]
        
        # Pick a random different context as negative
        wrong_context = random.choice([c for c in all_contexts if c != correct_context])
        
        negatives.append(InputExample(
            texts=[question, wrong_context],
            label=0.0  # Low similarity (negative)
        ))
    
    print(f"[*] Created {len(negatives)} hard negative examples")
    return negatives


def finetune_model(
    examples: List[InputExample],
    base_model: str = BASE_MODEL,
    output_dir: str = OUTPUT_DIR,
    epochs: int = 3,
    batch_size: int = 16,
    warmup_ratio: float = 0.1,
):
    """
    Fine-tune the embedding model using contrastive learning.
    """
    print(f"\n[*] Loading base model: {base_model}")
    model = SentenceTransformer(base_model)
    
    # Create dataloader
    train_dataloader = DataLoader(examples, shuffle=True, batch_size=batch_size)
    
    # Use CosineSimilarityLoss for (text1, text2, similarity_score) triplets
    train_loss = losses.CosineSimilarityLoss(model)
    
    # Calculate warmup steps
    warmup_steps = int(len(train_dataloader) * epochs * warmup_ratio)
    
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
    parser = argparse.ArgumentParser(description="Fine-tune embedding model")
    parser.add_argument("--epochs", "-e", type=int, default=3, help="Training epochs")
    parser.add_argument("--batch-size", "-b", type=int, default=16, help="Batch size")
    parser.add_argument("--dataset", "-d", type=str, default=DATASET_PATH)
    parser.add_argument("--output", "-o", type=str, default=OUTPUT_DIR)
    
    args = parser.parse_args()
    
    if not SENTENCE_TRANSFORMERS_AVAILABLE:
        print("[X] Cannot proceed without sentence-transformers")
        sys.exit(1)
    
    # Check dataset exists
    if not Path(args.dataset).exists():
        print(f"[X] Dataset not found: {args.dataset}")
        print("    Run: python scripts/generate_synthetic_dataset.py first")
        sys.exit(1)
    
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
        output_dir=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
    )
    
    print("\n" + "="*50)
    print("[+] Fine-tuning complete!")
    print("="*50)
    print(f"\nTo use the fine-tuned model, update your config:")
    print(f"  EMBEDDING_MODEL={args.output}")
    print(f"\nOr load it directly:")
    print(f"  model = SentenceTransformer('{args.output}')")


if __name__ == "__main__":
    main()

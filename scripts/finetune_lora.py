"""
LoRA Fine-Tuning Script for RAG LLM.

Fine-tunes a language model using LoRA (Low-Rank Adaptation) for improved
RAG responses. Supports Qwen, Llama, and Mistral models.

Hardware Requirements:
- GPU with 16GB+ VRAM (24GB+ recommended for Qwen 7B)
- For 8GB VRAM: Use --load-in-4bit

Usage:
    python scripts/finetune_lora.py \\
        --model "Qwen/Qwen2.5-7B-Instruct" \\
        --dataset "data/lora_dataset.json" \\
        --output "models/lora_rag" \\
        --epochs 3

    # For limited VRAM (8-12GB):
    python scripts/finetune_lora.py --load-in-4bit --batch-size 2
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional

# Check dependencies
try:
    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        TrainingArguments,
        BitsAndBytesConfig
    )
    from peft import (
        LoraConfig,
        get_peft_model,
        prepare_model_for_kbit_training,
        TaskType
    )
    from datasets import Dataset
    from trl import SFTTrainer, SFTConfig
except ImportError as e:
    print(f"[X] Missing dependency: {e}")
    print("    Run: pip install -r scripts/requirements-finetune.txt")
    sys.exit(1)

# Default configurations
DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
DEFAULT_OUTPUT = "models/lora_rag"

# LoRA configuration optimized for RAG
LORA_CONFIG = {
    "r": 16,                # Rank - affects capacity
    "lora_alpha": 32,       # Scaling factor (typically 2*r)
    "lora_dropout": 0.05,   # Dropout for regularization
    "bias": "none",
    "task_type": TaskType.CAUSAL_LM
}

# Model-specific target modules
TARGET_MODULES = {
    "qwen": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "llama": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "mistral": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "default": ["q_proj", "v_proj"]  # Conservative default
}


def get_target_modules(model_name: str) -> List[str]:
    """Get appropriate target modules based on model architecture."""
    model_lower = model_name.lower()
    for key in TARGET_MODULES:
        if key in model_lower:
            return TARGET_MODULES[key]
    return TARGET_MODULES["default"]


def load_dataset(path: str, format_type: str = "auto") -> Dataset:
    """Load and prepare training dataset."""
    print(f"[*] Loading dataset from: {path}")
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Detect format
    if isinstance(data, dict):
        if "alpaca" in data:
            examples = data["alpaca"]
            format_type = "alpaca"
        elif "sharegpt" in data:
            examples = data["sharegpt"]
            format_type = "sharegpt"
        else:
            examples = list(data.values())[0] if data else []
    else:
        examples = data
    
    print(f"[*] Detected format: {format_type}")
    print(f"[*] Total examples: {len(examples)}")
    
    # Convert to unified format for training
    processed = []
    
    for ex in examples:
        if format_type == "sharegpt" or "conversations" in ex:
            # ShareGPT format
            text = ""
            for msg in ex.get("conversations", []):
                role = msg.get("from", "")
                value = msg.get("value", "")
                if role == "system":
                    text += f"<|im_start|>system\n{value}<|im_end|>\n"
                elif role == "human":
                    text += f"<|im_start|>user\n{value}<|im_end|>\n"
                elif role == "gpt":
                    text += f"<|im_start|>assistant\n{value}<|im_end|>\n"
            processed.append({"text": text})
        else:
            # Alpaca format
            instruction = ex.get("instruction", "")
            input_text = ex.get("input", "")
            output = ex.get("output", "")
            
            if input_text:
                prompt = f"<|im_start|>user\n{instruction}\n\nContexto:\n{input_text}<|im_end|>\n"
            else:
                prompt = f"<|im_start|>user\n{instruction}<|im_end|>\n"
            
            text = f"<|im_start|>system\nEres un asistente RAG empresarial que responde basándose en documentos.<|im_end|>\n{prompt}<|im_start|>assistant\n{output}<|im_end|>"
            processed.append({"text": text})
    
    return Dataset.from_list(processed)


def setup_model_and_tokenizer(
    model_name: str,
    load_in_4bit: bool = False,
    load_in_8bit: bool = False
) -> tuple:
    """Load model and tokenizer with optional quantization."""
    
    print(f"[*] Loading model: {model_name}")
    
    # Quantization config
    bnb_config = None
    if load_in_4bit:
        print("[*] Using 4-bit quantization (QLoRA)")
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16
        )
    elif load_in_8bit:
        print("[*] Using 8-bit quantization")
        bnb_config = BitsAndBytesConfig(load_in_8bit=True)
    
    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True
    )
    
    # Set padding token if not set
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    # Load model
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16 if not bnb_config else None
    )
    
    # Prepare for training
    if bnb_config:
        model = prepare_model_for_kbit_training(model)
    
    model.config.use_cache = False  # Required for gradient checkpointing
    
    return model, tokenizer


def setup_lora(model, model_name: str, lora_r: int = 16, lora_alpha: int = 32):
    """Apply LoRA configuration to model."""
    
    target_modules = get_target_modules(model_name)
    print(f"[*] Target modules: {target_modules}")
    
    config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=LORA_CONFIG["lora_dropout"],
        bias=LORA_CONFIG["bias"],
        task_type=LORA_CONFIG["task_type"],
        target_modules=target_modules
    )
    
    model = get_peft_model(model, config)
    
    # Print trainable parameters
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"[*] Trainable parameters: {trainable_params:,} ({100 * trainable_params / total_params:.2f}%)")
    
    return model


def train(
    model,
    tokenizer,
    dataset: Dataset,
    output_dir: str,
    epochs: int = 3,
    batch_size: int = 4,
    gradient_accumulation: int = 4,
    learning_rate: float = 2e-4,
    max_seq_length: int = 2048,
    logging_steps: int = 10,
    save_steps: int = 100
):
    """Run the training loop."""
    
    print(f"\n[*] Training configuration:")
    print(f"    - Epochs: {epochs}")
    print(f"    - Batch size: {batch_size}")
    print(f"    - Gradient accumulation: {gradient_accumulation}")
    print(f"    - Effective batch: {batch_size * gradient_accumulation}")
    print(f"    - Learning rate: {learning_rate}")
    print(f"    - Max sequence length: {max_seq_length}")
    
    # TRL 0.26+ uses SFTConfig for training configuration
    sft_config = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation,
        gradient_checkpointing=True,
        learning_rate=learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.1,
        logging_steps=logging_steps,
        save_steps=save_steps,
        save_total_limit=3,
        bf16=torch.cuda.is_bf16_supported(),
        fp16=not torch.cuda.is_bf16_supported(),
        optim="paged_adamw_8bit",
        report_to="none",
        push_to_hub=False,
        dataset_text_field="text",
        packing=False
    )
    
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        args=sft_config,
        processing_class=tokenizer,
    )
    
    print("\n[*] Starting training...")
    trainer.train()
    
    # Save the adapter
    print(f"\n[*] Saving LoRA adapter to: {output_dir}")
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    
    return trainer


def main():
    parser = argparse.ArgumentParser(description="Fine-tune LLM with LoRA for RAG")
    
    # Model arguments
    parser.add_argument("--model", "-m", type=str, default=DEFAULT_MODEL,
                       help="Base model name or path")
    parser.add_argument("--dataset", "-d", type=str, required=True,
                       help="Path to training dataset JSON")
    parser.add_argument("--output", "-o", type=str, default=DEFAULT_OUTPUT,
                       help="Output directory for LoRA adapter")
    
    # Training arguments
    parser.add_argument("--epochs", "-e", type=int, default=3,
                       help="Number of training epochs")
    parser.add_argument("--batch-size", "-b", type=int, default=4,
                       help="Batch size per device")
    parser.add_argument("--gradient-accumulation", "-g", type=int, default=4,
                       help="Gradient accumulation steps")
    parser.add_argument("--learning-rate", "-lr", type=float, default=2e-4,
                       help="Learning rate")
    parser.add_argument("--max-seq-length", type=int, default=2048,
                       help="Maximum sequence length")
    
    # LoRA arguments
    parser.add_argument("--lora-r", type=int, default=16,
                       help="LoRA rank")
    parser.add_argument("--lora-alpha", type=int, default=32,
                       help="LoRA alpha (scaling factor)")
    
    # Quantization
    parser.add_argument("--load-in-4bit", action="store_true",
                       help="Load model in 4-bit (QLoRA)")
    parser.add_argument("--load-in-8bit", action="store_true",
                       help="Load model in 8-bit")
    
    args = parser.parse_args()
    
    # Validate
    if not Path(args.dataset).exists():
        print(f"[X] Dataset not found: {args.dataset}")
        print("    Run: python scripts/generate_lora_dataset.py first")
        sys.exit(1)
    
    # Check CUDA
    if not torch.cuda.is_available():
        print("[X] CUDA not available. GPU required for training.")
        sys.exit(1)
    
    print("=" * 60)
    print("  LoRA Fine-Tuning for RAG")
    print("=" * 60)
    print(f"  Model: {args.model}")
    print(f"  GPU: {torch.cuda.get_device_name(0)}")
    print(f"  VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
    print("=" * 60)
    
    # Load dataset
    dataset = load_dataset(args.dataset)
    
    # Setup model
    model, tokenizer = setup_model_and_tokenizer(
        args.model,
        load_in_4bit=args.load_in_4bit,
        load_in_8bit=args.load_in_8bit
    )
    
    # Apply LoRA
    model = setup_lora(model, args.model, args.lora_r, args.lora_alpha)
    
    # Train
    os.makedirs(args.output, exist_ok=True)
    trainer = train(
        model=model,
        tokenizer=tokenizer,
        dataset=dataset,
        output_dir=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        gradient_accumulation=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        max_seq_length=args.max_seq_length
    )
    
    print("\n" + "=" * 60)
    print("  Training Complete!")
    print("=" * 60)
    print(f"\n  LoRA adapter saved to: {args.output}")
    print("\n  Next steps:")
    print("    1. Merge adapter: python scripts/convert_lora_to_ollama.py")
    print("    2. Or test directly with: python scripts/test_lora.py")
    print("=" * 60)


if __name__ == "__main__":
    main()

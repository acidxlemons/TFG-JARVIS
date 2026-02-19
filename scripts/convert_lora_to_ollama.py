"""
Convert LoRA Adapter to Ollama Model.

Merges LoRA weights with base model and exports to GGUF format
for use with Ollama.

Usage:
    python scripts/convert_lora_to_ollama.py \\
        --base "Qwen/Qwen2.5-7B-Instruct" \\
        --lora "models/lora_rag" \\
        --output "models/merged_model"
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
except ImportError as e:
    print(f"[X] Missing dependency: {e}")
    print("    Run: pip install -r scripts/requirements-finetune.txt")
    sys.exit(1)


def merge_lora(base_model: str, lora_path: str, output_path: str):
    """Merge LoRA adapter with base model."""
    
    print(f"[*] Loading base model: {base_model}")
    
    # Load base model
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True
    )
    
    tokenizer = AutoTokenizer.from_pretrained(
        base_model,
        trust_remote_code=True
    )
    
    print(f"[*] Loading LoRA adapter: {lora_path}")
    
    # Load LoRA adapter
    model = PeftModel.from_pretrained(model, lora_path)
    
    print("[*] Merging weights...")
    
    # Merge and unload
    model = model.merge_and_unload()
    
    print(f"[*] Saving merged model to: {output_path}")
    
    # Save merged model
    os.makedirs(output_path, exist_ok=True)
    model.save_pretrained(output_path)
    tokenizer.save_pretrained(output_path)
    
    print("[+] Merge complete!")
    return output_path


def convert_to_gguf(model_path: str, output_path: str, quantization: str = "q8_0"):
    """Convert HuggingFace model to GGUF format for Ollama."""
    
    gguf_path = Path(output_path) / f"model-{quantization}.gguf"
    
    print(f"\n[*] Converting to GGUF format: {quantization}")
    print(f"[*] Output: {gguf_path}")
    
    # Check if llama.cpp convert script is available
    convert_script = "convert_hf_to_gguf.py"
    
    # Try to find llama.cpp installation
    llama_cpp_paths = [
        Path.home() / "llama.cpp",
        Path("/usr/local/llama.cpp"),
        Path("C:/llama.cpp"),
        Path(os.environ.get("LLAMA_CPP_PATH", ""))
    ]
    
    llama_cpp = None
    for p in llama_cpp_paths:
        if (p / convert_script).exists():
            llama_cpp = p
            break
    
    if llama_cpp:
        # Use llama.cpp convert script
        cmd = [
            sys.executable,
            str(llama_cpp / convert_script),
            model_path,
            "--outfile", str(gguf_path),
            "--outtype", quantization
        ]
        print(f"[*] Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
    else:
        print("[!] llama.cpp not found. Using alternative method...")
        print("[!] Install llama.cpp: git clone https://github.com/ggerganov/llama.cpp")
        print()
        print("    Manual conversion steps:")
        print(f"    1. cd llama.cpp")
        print(f"    2. python convert_hf_to_gguf.py {model_path} --outfile {gguf_path}")
        print(f"    3. ./llama-quantize {gguf_path} {gguf_path.with_suffix('')}-{quantization}.gguf {quantization}")
        return None
    
    return str(gguf_path)


def create_modelfile(model_name: str, gguf_path: str, output_dir: str):
    """Create Ollama Modelfile."""
    
    modelfile_content = f'''# RAG Fine-tuned Model
FROM {gguf_path}

# Model parameters optimized for RAG
PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 4096

# System prompt for RAG
SYSTEM """Eres un asistente RAG empresarial. Tu función es responder preguntas basándote en el contexto de documentos proporcionado.

Instrucciones:
1. Responde ÚNICAMENTE basándote en la información del contexto
2. Si no encuentras información relevante, indícalo claramente
3. Cita las fuentes al final de tu respuesta: [Fuente: documento, página]
4. Usa un tono profesional y estructurado
5. Responde siempre en español
"""

# License
LICENSE """
Model fine-tuned for internal RAG use.
Base model: {model_name}
"""
'''
    
    modelfile_path = Path(output_dir) / "Modelfile"
    
    with open(modelfile_path, "w", encoding="utf-8") as f:
        f.write(modelfile_content)
    
    print(f"[+] Modelfile created: {modelfile_path}")
    return str(modelfile_path)


def create_ollama_model(modelfile_path: str, ollama_name: str):
    """Create Ollama model from Modelfile."""
    
    print(f"\n[*] Creating Ollama model: {ollama_name}")
    
    cmd = ["ollama", "create", ollama_name, "-f", modelfile_path]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(result.stdout)
        print(f"[+] Model created successfully: {ollama_name}")
        print(f"\n    Test with: ollama run {ollama_name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[X] Error creating Ollama model: {e.stderr}")
        return False
    except FileNotFoundError:
        print("[X] Ollama CLI not found. Make sure Ollama is installed and in PATH.")
        print("    Install: https://ollama.ai/download")
        return False


def main():
    parser = argparse.ArgumentParser(description="Convert LoRA adapter to Ollama model")
    
    parser.add_argument("--base", "-b", type=str, required=True,
                       help="Base model name (e.g., Qwen/Qwen2.5-7B-Instruct)")
    parser.add_argument("--lora", "-l", type=str, required=True,
                       help="Path to LoRA adapter directory")
    parser.add_argument("--output", "-o", type=str, default="models/merged_model",
                       help="Output directory for merged model")
    parser.add_argument("--quantization", "-q", type=str, default="q8_0",
                       choices=["q4_0", "q4_1", "q5_0", "q5_1", "q8_0", "f16"],
                       help="GGUF quantization type")
    parser.add_argument("--ollama-name", "-n", type=str, default="rag-model-ft",
                       help="Name for Ollama model")
    parser.add_argument("--skip-merge", action="store_true",
                       help="Skip merge step (use if already merged)")
    parser.add_argument("--skip-gguf", action="store_true",
                       help="Skip GGUF conversion (manual conversion)")
    
    args = parser.parse_args()
    
    # Validate paths
    if not Path(args.lora).exists():
        print(f"[X] LoRA adapter not found: {args.lora}")
        sys.exit(1)
    
    print("=" * 60)
    print("  LoRA to Ollama Conversion")
    print("=" * 60)
    print(f"  Base model: {args.base}")
    print(f"  LoRA adapter: {args.lora}")
    print(f"  Output: {args.output}")
    print(f"  Quantization: {args.quantization}")
    print("=" * 60)
    
    # Step 1: Merge LoRA
    if not args.skip_merge:
        merged_path = merge_lora(args.base, args.lora, args.output)
    else:
        merged_path = args.output
        print(f"[*] Skipping merge, using: {merged_path}")
    
    # Step 2: Convert to GGUF
    if not args.skip_gguf:
        gguf_path = convert_to_gguf(merged_path, args.output, args.quantization)
        
        if not gguf_path:
            print("\n[!] GGUF conversion requires llama.cpp. See instructions above.")
            print("[*] After converting manually, run with --skip-gguf to continue")
            sys.exit(0)
    else:
        # Find existing GGUF
        gguf_files = list(Path(args.output).glob("*.gguf"))
        if gguf_files:
            gguf_path = str(gguf_files[0])
            print(f"[*] Using existing GGUF: {gguf_path}")
        else:
            print("[X] No GGUF file found in output directory")
            sys.exit(1)
    
    # Step 3: Create Modelfile
    modelfile_path = create_modelfile(args.base, gguf_path, args.output)
    
    # Step 4: Create Ollama model
    create_ollama_model(modelfile_path, args.ollama_name)
    
    print("\n" + "=" * 60)
    print("  Conversion Complete!")
    print("=" * 60)
    print(f"\n  Ollama model: {args.ollama_name}")
    print(f"\n  To use in docker-compose, update litellm config:")
    print(f"    model: ollama/{args.ollama_name}")
    print("=" * 60)


if __name__ == "__main__":
    main()

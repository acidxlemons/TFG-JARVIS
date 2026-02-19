#!/usr/bin/env bash
# scripts/pull_models.sh
set -euo pipefail

API="http://ollama:11434"
MAX_RETRIES=30
RETRY_DELAY=5

echo "Esperando a Ollama..."
retries=0
until curl -sf "${API}/api/tags" >/dev/null 2>&1; do
  retries=$((retries + 1))
  if [ $retries -ge $MAX_RETRIES ]; then
    echo "Ollama no respondió después de $MAX_RETRIES intentos"
    exit 1
  fi
  echo "  Reintento $retries/$MAX_RETRIES..."
  sleep $RETRY_DELAY
done

echo "Ollama disponible"
echo ""
echo "Descargando modelos..."

# 👇AÑADIR: función helper para descargas con retry
pull_model() {
  local model=$1
  echo "  • Descargando $model..."
  
  # Retry loop por si falla la descarga
  local pull_retries=0
  local max_pull_retries=3
  
  until curl -sf -X POST "${API}/api/pull" -d "{\"name\": \"${model}\"}" >/dev/null 2>&1; do
    pull_retries=$((pull_retries + 1))
    if [ $pull_retries -ge $max_pull_retries ]; then
      echo "    No se pudo descargar $model tras $max_pull_retries intentos"
      return 1
    fi
    echo "    Reintentando descarga $pull_retries/$max_pull_retries..."
    sleep 5
  done
  
  echo "   $model descargado"
  return 0
}

# Descargar modelos
pull_model "llama3.1:8b-instruct-q8_0"
pull_model "llama3.1:8b-instruct-q4_0"

# Modelo de visión (opcional)
if [ "${DOWNLOAD_VISION_MODEL:-false}" = "true" ]; then
  pull_model "llava:13b"
fi

echo ""
echo "Todos los modelos listos"

# Listar modelos disponibles
echo ""
echo "Modelos disponibles:"
curl -sf "${API}/api/tags" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('models', []):
    print(f\"  • {m['name']}\")
"
# services/indexer/Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Dependencias del sistema para pdf2image/poppler y Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    poppler-utils \
    ghostscript \
    libgl1 \
    tesseract-ocr \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requisitos
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Código en paquete Python "app"
COPY app /app/app

# Carpeta a vigilar
RUN mkdir -p /app/watch

# Puerto del servicio
EXPOSE 8001

# Variables por defecto
ENV BACKEND_URL="http://rag-backend:8000" \
    INDEX_MODE="backend" \
    WATCH_FOLDER="/app/watch" \
    SYNC_INTERVAL="300" \
    LOG_LEVEL="INFO" \
    OCR_USE_GPU="false"

# Lanzar API del indexer (importa app desde /app)
CMD ["uvicorn", "app.main:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8001"]

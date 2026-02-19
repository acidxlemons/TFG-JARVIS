# ============================================
# MULTI-STAGE BUILD (GPU - CUDA 11.8 + cuDNN8)
# ============================================

# -------- Stage 1: builder --------
FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04 AS builder

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=on

# Python 3.10 + toolchain
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip python3-dev \
    build-essential gcc g++ git wget curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements.txt ./requirements.txt

# Instala deps Python
RUN python3 -m pip install --upgrade pip && \
    pip install --no-cache-dir --user -r requirements.txt

# (OPCIONAL) Embeddings GPU (PyTorch CUDA 12.1) – si falla, no rompas build
RUN python3 -m pip install --user --index-url https://download.pytorch.org/whl/cu121 torch torchvision torchaudio || true


# -------- Stage 2: runtime --------
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04 AS runtime

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=on \
    PATH="/root/.local/bin:${PATH}"

# Python runtime + libs nativas
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    poppler-utils \
    tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
    libgomp1 \
    curl \
    fonts-dejavu-core \
    libglib2.0-0 libgl1 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade pip

# Copia site-packages del builder
COPY --from=builder /root/.local /root/.local

WORKDIR /workspace
RUN mkdir -p /workspace/app/cache/ocr

# (Opcional) Playwright
ARG INSTALL_PLAYWRIGHT=false
RUN if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then \
      python3 -m pip install --user playwright && \
      python3 -m playwright install --with-deps chromium && \
      rm -rf /root/.cache/ms-playwright/*.zip; \
    fi

EXPOSE 8000

# Healthcheck del backend
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

CMD ["bash", "-lc", "echo 'Use docker-compose command' && sleep infinity"]

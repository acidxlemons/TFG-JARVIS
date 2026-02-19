# backend/app/main.py
"""
Enterprise RAG System API — Punto de entrada principal

Este archivo es el ORQUESTADOR de la aplicación. No contiene lógica de negocio.
Su responsabilidad es:

1. Configurar la aplicación FastAPI (título, docs, tags).
2. Registrar middleware (CORS, métricas Prometheus, rate limiting).
3. Incluir los routers de cada dominio.
4. Definir el lifecycle (startup/shutdown).

La lógica de negocio está distribuida en módulos especializados:
- schemas/      → Modelos Pydantic (request/response)
- services/     → Lógica de negocio (chat, detección de modo, caché)
- api/          → Routers HTTP (chat, documentos, webhooks, sistema)
- state.py      → Estado global y configuración
- metrics.py    → Definiciones de métricas Prometheus

Arquitectura:
    main.py (orquestador)
    ├── api/chat.py          → POST /chat, POST /chat/stream
    ├── api/documents_endpoints.py → CRUD de documentos
    ├── api/webhooks.py      → Webhooks de SharePoint
    ├── api/system.py        → /health, /metrics, /
    ├── api/scrape.py        → /scrape/analyze, /scrape/index (existente)
    ├── api/web_search.py    → /web-search (existente)
    ├── api/search.py        → /api/v1/search (existente)
    └── api/external_data.py → /boe/... (existente)
"""

import os
import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from qdrant_client import QdrantClient

# Componentes internos
from app.core.rag.retriever import RAGRetriever
from app.core.memory.manager import MemoryManager
from app.core.agent.base import RAGAgent
from app.processing.ocr.paddle_ocr import OCRPipeline
from app.processing.chunking.smart_chunker import SmartChunker
from app.integrations.sharepoint.client import SharePointClient

# Estado global y configuración
from app.state import app_state, LITELLM_BASE_URL, LITELLM_API_KEY, LLM_MODEL

# Métricas Prometheus
from app.metrics import http_requests_total, http_request_duration_seconds

# Routers de la API
from app.api import scrape as scrape_api
from app.api import search as search_api
from app.api import web_search
from app.api import external_data
from app.api import chat as chat_router
from app.api import documents_endpoints
from app.api import webhooks as webhooks_router
from app.api import system as system_router


# ======================================================
# LOGGING
# ======================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


# ======================================================
# HELPERS
# ======================================================

def _bool_env(name: str, default: bool = False) -> bool:
    """Lee una variable de entorno como booleano."""
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


# ======================================================
# LIFECYCLE (startup / shutdown)
# ======================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialización y limpieza de la aplicación."""
    logger.info("🚀 Iniciando aplicación RAG...")

    # Qdrant
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    app_state.qdrant = QdrantClient(url=qdrant_url)
    logger.info(f"✓ Qdrant conectado: {qdrant_url}")

    # Retriever
    default_tenant_id = os.getenv("DEFAULT_TENANT_ID")
    app_state.retriever = RAGRetriever(
        qdrant_client=app_state.qdrant,
        collection_name=os.getenv("QDRANT_COLLECTION", "documents"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"),
        top_k=int(os.getenv("RAG_TOP_K", "5")),
        score_threshold=float(os.getenv("RAG_SCORE_THRESHOLD", "0.7")),
        tenant_id=default_tenant_id,
    )
    logger.info("✓ RAG Retriever inicializado")

    # Memory Manager
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        logger.warning("POSTGRES_URL no establecido.")
    app_state.memory = MemoryManager(database_url=postgres_url)
    logger.info("✓ Memory Manager inicializado")

    # RAG Agent (legacy, mantenido por compatibilidad)
    app_state.agent = RAGAgent(
        retriever=app_state.retriever,
        memory_manager=app_state.memory,
        llm_base_url=os.getenv("LITELLM_URL", "http://localhost:4000"),
        llm_api_key=LITELLM_API_KEY or "not-configured",
        model_name=LLM_MODEL,
        default_tenant_id=default_tenant_id,
    )
    logger.info("✓ RAG Agent inicializado")

    # OCR Pipeline
    app_state.ocr_pipeline = OCRPipeline(
        num_workers=int(os.getenv("OCR_NUM_WORKERS", "6")),
        use_gpu=_bool_env("OCR_USE_GPU", True),
    )
    logger.info("✓ OCR Pipeline inicializado")

    # Chunker
    app_state.chunker = SmartChunker(
        chunk_size=int(os.getenv("CHUNK_SIZE", "500")),
        overlap=int(os.getenv("CHUNK_OVERLAP", "50")),
    )
    logger.info("✓ Smart Chunker inicializado")

    # SharePoint (opcional)
    app_state.sharepoint = None
    if os.getenv("SHAREPOINT_TENANT_ID"):
        app_state.sharepoint = SharePointClient(
            tenant_id=os.getenv("SHAREPOINT_TENANT_ID"),
            client_id=os.getenv("SHAREPOINT_CLIENT_ID"),
            client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET"),
            site_id=os.getenv("SHAREPOINT_SITE_ID"),
            folder_path=os.getenv("SHAREPOINT_FOLDER_PATH", "Documents"),
        )
        logger.info("✓ SharePoint Client inicializado")

    logger.info("✅ Aplicación lista")

    yield

    # Cleanup
    logger.info("Cerrando aplicación...")
    try:
        app_state.ocr_pipeline.shutdown()
    except Exception as e:
        logger.warning(f"Error al cerrar OCR Pipeline: {e}")


# ======================================================
# APP FASTAPI
# ======================================================

tags_metadata = [
    {"name": "Chat", "description": "Endpoints de conversación con modos RAG y chat normal"},
    {"name": "Search", "description": "Búsqueda directa en documentos (semántica, keyword, híbrida)"},
    {"name": "Documents", "description": "Gestión de documentos: upload, list, delete, status"},
    {"name": "Web", "description": "Búsqueda en internet y web scraping"},
    {"name": "System", "description": "Health checks y monitoreo del sistema"},
]

app = FastAPI(
    title="Enterprise RAG System API",
    version="2.1.0",
    description="""
## 🚀 Enterprise RAG System API

Sistema RAG (Retrieval Augmented Generation) empresarial con:

- **🔍 Búsqueda Híbrida**: Combina embeddings semánticos + keywords (BM25)
- **📄 OCR Inteligente**: PaddleOCR con soporte GPU para PDFs escaneados
- **💬 Chat con Memoria**: Contexto conversacional persistente
- **🌐 Web Search**: Integración con DuckDuckGo
- **📊 Multi-tenant**: Aislamiento de datos por tenant
- **⚡ Streaming**: Respuestas en tiempo real via SSE

### Autenticación
Las requests requieren el header `X-Tenant-Id` para multi-tenancy.
    """,
    openapi_tags=tags_metadata,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ======================================================
# MIDDLEWARE
# ======================================================

# Rate Limiting (protección contra abuso)
rate_limit = os.getenv("RATE_LIMIT", "60/minute")
limiter = Limiter(key_func=get_remote_address, default_limits=[rate_limit])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
logger.info(f"Rate limiting configurado: {rate_limit}")

# CORS
allow_origins_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
allow_origins = [o.strip() for o in allow_origins_env.split(",")] if allow_origins_env else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def track_requests(request: Request, call_next):
    """Middleware: registra métricas Prometheus para cada request."""
    start_time = time.time()

    path = request.url.path
    if path.startswith("/documents/"):
        path = "/documents/{action}"
    elif path.startswith("/api/v1/"):
        path = "/api/v1/{endpoint}"

    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        status = 500
        raise
    finally:
        duration = time.time() - start_time
        if not path.startswith(("/metrics", "/docs", "/redoc")):
            http_requests_total.labels(
                method=request.method,
                endpoint=path,
                status=status
            ).inc()
            http_request_duration_seconds.labels(
                method=request.method,
                endpoint=path
            ).observe(duration)

    return response


# ======================================================
# ROUTERS
# ======================================================

# Chat (sync + streaming SSE)
app.include_router(chat_router.router, tags=["Chat"])

# Documents (upload, list, delete, stats, status)
app.include_router(documents_endpoints.router, tags=["Documents"])

# Webhooks (SharePoint notifications)
app.include_router(webhooks_router.router, tags=["Webhooks"])

# System (health, root, metrics)
app.include_router(system_router.router, tags=["System"])

# Scraping (existente)
app.include_router(scrape_api.router, tags=["Web"])

# Búsqueda híbrida v2 (existente)
app.include_router(search_api.router, tags=["Search"])

# Web search DuckDuckGo (existente)
app.include_router(web_search.router, tags=["Web"])

# External data BOE (existente)
app.include_router(external_data.router, tags=["External Data"])

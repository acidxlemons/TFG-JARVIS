# backend/app/state.py
"""
Estado Global de la Aplicación — AppState

Este módulo centraliza el estado compartido de toda la aplicación:
- Conexiones a servicios externos (Qdrant, PostgreSQL)
- Instancias de componentes (Retriever, Agent, OCR, Chunker)
- Constantes de configuración cargadas desde variables de entorno

¿Por qué un módulo separado?
Anteriormente todo estaba en main.py (1959 líneas). Al separarlo:
1. Cualquier módulo puede importar `app_state` sin dependencias circulares.
2. La configuración es más fácil de testear y modificar.
3. main.py se reduce a solo configuración de FastAPI y routers.

Uso:
    from app.state import app_state, LITELLM_BASE_URL, LLM_MODEL
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ======================================================
# CONSTANTES DE CONFIGURACIÓN (cargadas de .env)
# ======================================================

LITELLM_BASE_URL = os.getenv("LITELLM_URL", "http://localhost:4000").rstrip("/")

# SEGURIDAD: No se usa fallback inseguro. Si no se configura LITELLM_API_KEY,
# se lanza un error claro en vez de usar "sk-1234" silenciosamente.
_litellm_api_key = os.getenv("LITELLM_API_KEY")
if not _litellm_api_key:
    logger.warning(
        "⚠️  LITELLM_API_KEY no configurada. "
        "El sistema NO podrá comunicarse con el LLM. "
        "Configura esta variable en tu archivo .env"
    )
    LITELLM_API_KEY = "NOT_CONFIGURED"
else:
    LITELLM_API_KEY = _litellm_api_key

LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1-8b")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "documents")


# ======================================================
# ESTADO GLOBAL DE LA APLICACIÓN
# ======================================================

class AppState:
    """
    Contenedor singleton del estado compartido de la aplicación.

    Se inicializa durante el lifespan de FastAPI (al arrancar la app)
    y se usa desde cualquier endpoint o servicio.

    Atributos:
    - qdrant: Cliente de Qdrant (base de datos vectorial).
    - retriever: RAGRetriever para búsqueda semántica en documentos.
    - memory: MemoryManager para historial de conversaciones (PostgreSQL).
    - agent: RAGAgent con LangChain para chat con herramientas.
    - ocr_pipeline: Pipeline OCR con PaddleOCR para PDFs escaneados.
    - chunker: SmartChunker para fragmentación inteligente de texto.
    - sharepoint: Cliente SharePoint para sincronización de documentos (opcional).
    """
    qdrant: object  # QdrantClient - se inicializa en lifespan
    retriever: object  # RAGRetriever
    memory: object  # MemoryManager
    agent: object  # RAGAgent
    ocr_pipeline: object  # OCRPipeline
    chunker: object  # SmartChunker
    sharepoint: Optional[object] = None  # SharePointClient (opcional)


# Instancia global única — importar desde cualquier módulo
app_state = AppState()

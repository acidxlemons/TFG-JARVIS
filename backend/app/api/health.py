"""
backend/app/api/health.py

Health check endpoints
"""

from fastapi import APIRouter, HTTPException
from typing import Dict
import logging

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
async def health_check() -> Dict:
    """Health check básico"""
    return {"status": "healthy"}


@router.get("/health/detailed")
async def detailed_health() -> Dict:
    """Health check detallado con estado de servicios"""
    
    health_status = {
        "status": "healthy",
        "services": {},
    }

    # Check Qdrant
    try:
        from app.storage.qdrant_client import get_qdrant_client
        qdrant = get_qdrant_client()
        collections = qdrant.get_collections()
        health_status["services"]["qdrant"] = {
            "status": "healthy",
            "collections": len(collections.collections),
        }
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["services"]["qdrant"] = {
            "status": "unhealthy",
            "error": str(e),
        }

    # Check Embeddings
    try:
        from app.processing.embeddings.sentence_transformer import get_embedder
        embedder = get_embedder()
        health_status["services"]["embeddings"] = {
            "status": "healthy",
            "model": embedder.model_name,
            "dimension": embedder.dimension,
        }
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["services"]["embeddings"] = {
            "status": "unhealthy",
            "error": str(e),
        }

    # Check OCR
    try:
        from app.processing.ocr.paddle_ocr import get_ocr_processor
        ocr = get_ocr_processor()
        health_status["services"]["ocr"] = {
            "status": "healthy",
            "languages": ocr.languages,
        }
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["services"]["ocr"] = {
            "status": "unhealthy",
            "error": str(e),
        }

    return health_status
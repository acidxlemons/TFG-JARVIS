"""
backend/app/storage/qdrant_client.py

Qdrant client helper with automatic collection bootstrap.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

logger = logging.getLogger(__name__)


_qdrant_client: Optional[QdrantClient] = None


def get_qdrant_client(force_recreate: bool = False) -> QdrantClient:
    """
    Return a singleton Qdrant client. Creates it on first use and ensures the
    configured collection exists.
    """
    global _qdrant_client

    if _qdrant_client is None or force_recreate:
        url = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")
        api_key = os.getenv("QDRANT_API_KEY")
        prefer_grpc = os.getenv("QDRANT_PREFER_GRPC", "false").lower() in {"1", "true", "yes"}
        grpc_port = os.getenv("QDRANT_GRPC_PORT")

        client_kwargs = {"url": url}
        if api_key:
            client_kwargs["api_key"] = api_key
        if prefer_grpc:
            client_kwargs["prefer_grpc"] = True
            if grpc_port:
                client_kwargs["grpc_port"] = int(grpc_port)

        logger.info("Connecting to Qdrant: %s", url)
        _qdrant_client = QdrantClient(**client_kwargs)
        _ensure_collection(_qdrant_client)

    return _qdrant_client


def _ensure_collection(client: QdrantClient) -> None:
    """Create the collection if it does not exist yet."""
    collection_name = os.getenv("QDRANT_COLLECTION", "documents")

    collections = client.get_collections().collections
    exists = any(c.name == collection_name for c in collections)

    if exists:
        logger.info("Collection '%s' already exists", collection_name)
        return

    vector_dim = _resolve_vector_dim()
    logger.info("Creating collection '%s' (dim=%s)", collection_name, vector_dim)
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_dim, distance=Distance.COSINE),
    )
    logger.info("Collection '%s' created", collection_name)


def _resolve_vector_dim() -> int:
    """
    Determine the embedding dimension either from ENV or by loading the embedder.
    """
    env_value = os.getenv("EMBEDDING_DIMENSION")
    if env_value:
        return int(env_value)

    try:
        from app.processing.embeddings.sentence_transformer import get_embedder
    except Exception as exc:  # pragma: no cover - import edge case
        raise RuntimeError(
            "Failed to import embedding generator. Set EMBEDDING_DIMENSION "
            "to skip auto-loading or ensure sentence_transformers is installed."
        ) from exc

    return get_embedder().dimension

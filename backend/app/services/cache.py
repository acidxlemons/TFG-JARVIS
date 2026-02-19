# backend/app/services/cache.py
"""
Servicio de Caché Redis — Cacheo de resultados de búsqueda RAG

Este módulo implementa una capa de caché usando Redis para evitar
búsquedas repetidas en Qdrant, mejorando los tiempos de respuesta
significativamente para queries frecuentes.

Qué se cachea:
- Resultados de búsqueda RAG (por hash de query + colecciones).
- TTL configurable por variable de entorno (default: 5 minutos).

Cuándo se invalida:
- Cuando se indexa un nuevo documento (cambio en la colección).
- Cuando se elimina un documento.
- Cuando el TTL expira naturalmente.

¿Por qué Redis?
Redis ya está desplegado en la infraestructura Docker del proyecto
(se usa para otros servicios). Aprovechar esta instancia existente
para cachear búsquedas es eficiente y no añade complejidad de infraestructura.

Uso:
    from app.services.cache import search_cache

    # Intentar obtener resultado cacheado
    cached = search_cache.get("mi query", ["documents", "webs"])
    if cached:
        return cached  # Respuesta inmediata sin buscar en Qdrant

    # Si no hay caché, buscar y cachear
    results = retriever.retrieve(...)
    search_cache.set("mi query", ["documents", "webs"], results)
"""

import os
import json
import hashlib
import logging
from typing import Optional, List, Any

logger = logging.getLogger(__name__)


# Configuración de caché
CACHE_TTL_SECONDS = int(os.getenv("RAG_CACHE_TTL_SECONDS", "300"))  # 5 minutos por defecto
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_ENABLED = os.getenv("RAG_CACHE_ENABLED", "true").lower() in {"true", "1", "yes"}


class SearchCache:
    """
    Caché Redis para resultados de búsqueda RAG.

    Funciona como un diccionario temporal: guarda resultados de búsqueda
    asociados a un hash único de la query + colecciones, con un tiempo
    de expiración (TTL) configurable.

    Si Redis no está disponible, el caché se desactiva silenciosamente
    (graceful degradation) y el sistema funciona igual que antes.
    """

    def __init__(self):
        """Inicializa la conexión Redis. Si falla, se desactiva el caché."""
        self._redis = None
        self._enabled = CACHE_ENABLED

        if not self._enabled:
            logger.info("RAG Cache desactivado por configuración (RAG_CACHE_ENABLED=false)")
            return

        try:
            import redis
            self._redis = redis.from_url(REDIS_URL, decode_responses=True)
            # Test de conexión
            self._redis.ping()
            logger.info(f"✓ RAG Cache Redis conectado (TTL={CACHE_TTL_SECONDS}s)")
        except ImportError:
            logger.warning("Paquete 'redis' no instalado. RAG Cache desactivado.")
            self._enabled = False
        except Exception as e:
            logger.warning(f"Redis no disponible ({e}). RAG Cache desactivado (graceful degradation).")
            self._enabled = False

    def _make_key(self, query: str, collections: List[str]) -> str:
        """
        Genera una clave única de caché basada en la query y colecciones.

        Usa SHA-256 para crear un hash determinista que identifica
        unívocamente la combinación query + colecciones buscadas.
        """
        raw = f"{query.strip().lower()}|{'|'.join(sorted(collections))}"
        return f"rag_cache:{hashlib.sha256(raw.encode()).hexdigest()}"

    def get(self, query: str, collections: List[str]) -> Optional[dict]:
        """
        Intenta recuperar resultados cacheados.

        Args:
            query: La query de búsqueda.
            collections: Las colecciones Qdrant buscadas.

        Returns:
            Diccionario con resultados si hay caché, None si no.
        """
        if not self._enabled or not self._redis:
            return None

        try:
            key = self._make_key(query, collections)
            cached = self._redis.get(key)
            if cached:
                logger.info(f"Cache HIT para query: '{query[:50]}...'")
                return json.loads(cached)
            logger.debug(f"Cache MISS para query: '{query[:50]}...'")
            return None
        except Exception as e:
            logger.warning(f"Error leyendo caché: {e}")
            return None

    def set(self, query: str, collections: List[str], data: dict) -> None:
        """
        Almacena resultados en caché con TTL.

        Args:
            query: La query de búsqueda.
            collections: Las colecciones Qdrant buscadas.
            data: Los resultados a cachear (deben ser JSON-serializables).
        """
        if not self._enabled or not self._redis:
            return

        try:
            key = self._make_key(query, collections)
            self._redis.setex(key, CACHE_TTL_SECONDS, json.dumps(data))
            logger.debug(f"Cacheado resultado para: '{query[:50]}...' (TTL={CACHE_TTL_SECONDS}s)")
        except Exception as e:
            logger.warning(f"Error escribiendo caché: {e}")

    def invalidate_collection(self, collection_name: str) -> int:
        """
        Invalida todos los cachés que involucren una colección específica.

        Se llama cuando se indexa o elimina un documento de esa colección,
        para asegurar que las próximas búsquedas reflejen los cambios.

        Args:
            collection_name: Nombre de la colección modificada.

        Returns:
            Número de claves invalidadas.
        """
        if not self._enabled or not self._redis:
            return 0

        try:
            # Invalidar de forma segura: borrar todas las claves rag_cache:*
            # En producción con muchas claves, se podría usar SCAN en vez de KEYS
            pattern = "rag_cache:*"
            keys = self._redis.keys(pattern)
            if keys:
                deleted = self._redis.delete(*keys)
                logger.info(f"Cache invalidado: {deleted} claves borradas (colección: {collection_name})")
                return deleted
            return 0
        except Exception as e:
            logger.warning(f"Error invalidando caché: {e}")
            return 0

    def clear_all(self) -> int:
        """
        Borra toda la caché RAG. Útil para mantenimiento.

        Returns:
            Número de claves borradas.
        """
        return self.invalidate_collection("*")


# Instancia global del caché — importar desde cualquier módulo
search_cache = SearchCache()

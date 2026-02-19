# backend/app/api/documents_endpoints.py
"""
Router de Documentos — Gestión de documentos indexados

Endpoints disponibles:
- POST /documents/upload: Sube y procesa un documento (background task).
- GET /documents/stats: Estadísticas de la colección (nº de chunks).
- GET /documents/list: Lista de documentos indexados en las colecciones del usuario.
- DELETE /documents/delete: Elimina un documento y todos sus chunks de Qdrant.
- POST /documents/status: Actualiza estado de ingestión (usado internamente).
- GET /documents/ingestion-status: Últimos estados de ingestión.
- DELETE /documents/cleanup-old-status: Limpia estados antiguos (mantenimiento).

Pipeline de procesamiento de documentos:
1. Recibe el archivo codificado en base64.
2. Decodifica y guarda como archivo temporal.
3. En background: detecta formato → OCR si necesario → chunking → embeddings → indexación en Qdrant.
4. Actualiza estado de ingestión en PostgreSQL.
"""

import os
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, BackgroundTasks, Query, Body

from app.schemas.documents import DocumentList
from app.state import app_state
from app.services.cache import search_cache

router = APIRouter()
logger = logging.getLogger(__name__)


# ======================================================
# BÚSQUEDA DIRECTA
# ======================================================

@router.post("/search", tags=["Search"])
async def search_documents(
    payload: dict = Body(...),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
    """
    Búsqueda directa en documentos (sin agente)
    payload esperado:
    {
        "query": "texto",
        "top_k": 5,
        "filter_by_filename": "algo.pdf",
        "exclude_ocr": false
    }
    """
    try:
        query = payload.get("query")
        if not isinstance(query, str) or not query.strip():
            raise HTTPException(
                status_code=400,
                detail="Field 'query' is required and must be a non-empty string",
            )

        raw_top_k = payload.get("top_k", 5)
        try:
            top_k = int(raw_top_k)
        except Exception:
            top_k = 5

        filter_by_filename = payload.get("filter_by_filename")
        exclude_ocr = bool(payload.get("exclude_ocr", False))

        results = app_state.retriever.retrieve(
            query=query,
            top_k=top_k,
            filter_by_source=None,
            filter_by_filenames=[filter_by_filename] if filter_by_filename else None,
            exclude_ocr=exclude_ocr,
            tenant_id=x_tenant_id or os.getenv("DEFAULT_TENANT_ID"),
        )

        return {
            "query": query,
            "results": [
                {
                    "text": r.text,
                    "score": r.score,
                    "filename": r.filename,
                    "page": r.page,
                    "citation": r.citation,
                    "from_ocr": r.from_ocr,
                }
                for r in results
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en búsqueda: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================
# UPLOAD DE DOCUMENTOS
# ======================================================

@router.post("/documents/upload", tags=["Documents"])
async def upload_document(
    background_tasks: BackgroundTasks,
    payload: dict = Body(...),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
    """
    Sube y procesa documento

    Espera un JSON:
    {
        "filename": "archivo.pdf",
        "content_base64": "...",
        "metadata": { ... }
    }
    """
    try:
        filename = payload.get("filename")
        content_base64 = payload.get("content_base64")
        metadata = payload.get("metadata") or {}

        if not isinstance(filename, str) or not filename.strip():
            raise HTTPException(
                status_code=400,
                detail="Field 'filename' is required and must be a non-empty string",
            )

        if not isinstance(content_base64, str) or not content_base64.strip():
            raise HTTPException(
                status_code=400,
                detail="Field 'content_base64' is required and must be a non-empty string",
            )

        if not isinstance(metadata, dict):
            raise HTTPException(
                status_code=400,
                detail="Field 'metadata' must be an object",
            )

        import base64
        from pathlib import Path
        import tempfile

        content = base64.b64decode(content_base64)

        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        background_tasks.add_task(
            process_document,
            file_path=tmp_path,
            filename=filename,
            metadata=metadata,
            tenant_id=x_tenant_id or os.getenv("DEFAULT_TENANT_ID"),
        )

        return {
            "status": "processing",
            "filename": filename,
            "message": "Documento en cola para procesamiento",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error subiendo documento: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def process_document(file_path: str, filename: str, metadata: dict, tenant_id: Optional[str]):
    """
    Procesa documento: OCR → Chunking → Vectorización → Qdrant
    Esta función se ejecuta en background.

    Pipeline:
    1. Detecta formato del archivo (.txt, .docx, .pdf, imágenes).
    2. Extrae texto (directo para texto plano, python-docx para Word, OCR para PDFs/imágenes).
    3. Fragmenta el texto en chunks semánticos con SmartChunker.
    4. Genera embeddings vectoriales con SentenceTransformer.
    5. Elimina chunks anteriores del mismo archivo (evita duplicados).
    6. Inserta nuevos puntos en Qdrant.
    7. Invalida la caché Redis para que las búsquedas reflejen el nuevo contenido.
    """
    from pathlib import Path
    from datetime import datetime
    from qdrant_client.models import PointStruct
    import uuid

    from app.processing.embeddings.sentence_transformer import embed_texts

    logger.info(f"Procesando documento: {filename}")

    # Status: Processing
    try:
        app_state.memory.update_ingestion_status(filename, "processing", "Iniciando procesamiento...")
    except Exception as e:
        logger.warning(f"No se pudo actualizar status inicial: {e}")

    try:
        from pathlib import Path as _Path
        suffix = _Path(file_path).suffix.lower()

        # 1) Texto plano: .txt / .md / .log
        if suffix in {".txt", ".md", ".log"}:
            logger.info(f"Leyendo texto plano de {filename}...")
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                pages = 1
                from_ocr = False
            except Exception as e:
                logger.error(f"Error leyendo texto plano de {filename}: {e}")
                text = ""
                pages = 0
                from_ocr = False

        # 2) Documentos Word: .doc / .docx
        elif suffix in {".doc", ".docx"}:
            logger.info(f"Extrayendo texto de documento Word: {filename}...")
            try:
                from docx import Document
                doc = Document(file_path)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                text = "\n".join(paragraphs)
                pages = max(1, len(paragraphs) // 30)
                from_ocr = False
                logger.info(f"Extraídos {len(paragraphs)} párrafos de {filename}")
            except Exception as e:
                logger.error(f"Error procesando Word {filename}: {e}")
                try:
                    logger.info(f"Fallback: intentando OCR para {filename}...")
                    result = app_state.ocr_pipeline.process_file(file_path)
                    text = result.text
                    pages = result.pages
                    from_ocr = True
                except Exception as e2:
                    logger.error(f"OCR fallback también falló para {filename}: {e2}")
                    text = ""
                    pages = 0
                    from_ocr = False

        else:
            # 3) Resto de formatos: PDF, imágenes, etc.
            needs_ocr = app_state.ocr_pipeline.needs_ocr(file_path)

            if needs_ocr:
                logger.info(f"Aplicando OCR a {filename}...")
                result = app_state.ocr_pipeline.process_file(file_path)
                text = result.text
                pages = result.pages
                from_ocr = True
            else:
                logger.info(f"Extrayendo texto nativo de {filename}...")
                from app.processing.ocr.paddle_ocr import extract_text_native
                text = extract_text_native(file_path)
                pages = max(1, text.count("=== PÁGINA ===")) if text else 0
                from_ocr = False

        if not text or len(text.strip()) < 50:
            logger.warning(f"Texto insuficiente en {filename}")
            Path(file_path).unlink(missing_ok=True)
            return

        # Chunking
        chunks = app_state.chunker.chunk_text(text, filename)
        logger.info(f"Generados {len(chunks)} chunks")

        # Vectorizar
        texts = [c["text"] for c in chunks]
        logger.info(f"Generando embeddings para {len(texts)} chunks...")
        embeddings = embed_texts(texts)

        # Timestamps
        now = datetime.utcnow()
        now_iso = now.isoformat() + "Z"
        now_ts = int(now.timestamp())

        # Preparar puntos para Qdrant
        points = []
        for chunk, embedding in zip(chunks, embeddings):
            payload = {
                "text": chunk["text"],
                "filename": filename,
                "source": metadata.get("source") or filename,
                "page": chunk["metadata"].get("page"),
                "chunk_index": chunk["metadata"].get("chunk_index"),
                "from_ocr": from_ocr,
                "ingested_at": now_iso,
                "ingested_at_ts": now_ts,
                "tenant_id": tenant_id,
                **metadata,
            }
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    payload=payload,
                )
            )

        # Determinar colección destino
        default_collection = os.getenv("QDRANT_COLLECTION", "documents")
        if tenant_id and tenant_id.startswith("documents_"):
            target_collection = tenant_id
            logger.info(f"Usando colección departamental: {target_collection}")
        else:
            target_collection = default_collection

        # Crear colección si no existe
        try:
            app_state.qdrant.get_collection(target_collection)
        except Exception:
            logger.info(f"Creando nueva colección: {target_collection}")
            from qdrant_client.models import VectorParams, Distance
            app_state.qdrant.create_collection(
                collection_name=target_collection,
                vectors_config=VectorParams(
                    size=len(embeddings[0]) if embeddings else 384,
                    distance=Distance.COSINE,
                ),
            )

        # Eliminar chunks anteriores del mismo archivo (evitar duplicados)
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            existing = app_state.qdrant.scroll(
                collection_name=target_collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="filename", match=MatchValue(value=filename))]
                ),
                limit=10000,
                with_payload=False,
                with_vectors=False,
            )
            if existing[0]:
                ids_to_delete = [p.id for p in existing[0]]
                app_state.qdrant.delete(
                    collection_name=target_collection,
                    points_selector=ids_to_delete,
                )
                logger.info(f"🗑️ Eliminados {len(ids_to_delete)} chunks antiguos de '{filename}'")
        except Exception as e:
            logger.warning(f"No se pudieron eliminar chunks anteriores de {filename}: {e}")

        # Insertar en Qdrant
        app_state.qdrant.upsert(
            collection_name=target_collection,
            points=points,
        )

        logger.info(f"✓ Documento procesado e indexado: {filename} ({len(points)} chunks)")

        # Invalidar caché Redis (las búsquedas anteriores ya no son válidas)
        search_cache.invalidate_collection(target_collection)

        # Status: Completed
        app_state.memory.update_ingestion_status(filename, "completed", f"Indexado correctamente ({len(points)} chunks)")

    except Exception as e:
        logger.error(f"Error procesando documento {filename}: {e}")
        try:
            app_state.memory.update_ingestion_status(filename, "failed", str(e))
        except:
            pass
    finally:
        from pathlib import Path as _Path2
        _Path2(file_path).unlink(missing_ok=True)


# ======================================================
# ESTADÍSTICAS
# ======================================================

@router.get("/documents/stats", tags=["Documents"])
async def get_documents_stats():
    """Estadísticas de documentos indexados (directo a Qdrant.count)"""
    try:
        collection_name = os.getenv("QDRANT_COLLECTION", "documents")

        res = app_state.qdrant.count(
            collection_name=collection_name,
            count_filter=None,
            exact=True,
        )

        if hasattr(res, "dict"):
            data = res.dict()
        elif hasattr(res, "__dict__"):
            data = res.__dict__
        elif isinstance(res, dict):
            data = res
        else:
            data = {"raw": str(res)}

        points_count = data.get("count")

        return {
            "collection_name": collection_name,
            "status": "ok",
            "points_count": points_count,
            "raw": data,
        }
    except Exception as e:
        logger.error(f"Error obteniendo stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================
# LISTADO
# ======================================================

@router.get("/documents/list", response_model=DocumentList)
async def list_documents(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    x_tenant_ids: Optional[str] = Header(None, alias="X-Tenant-Ids"),
):
    """Lista todos los documentos indexados en las colecciones del usuario."""
    try:
        collections_to_search = []
        if x_tenant_ids:
            collections_to_search = [c.strip() for c in x_tenant_ids.split(",") if c.strip()]
            logger.info(f"Listando documentos de {len(collections_to_search)} colecciones")
        elif x_tenant_id:
            collections_to_search = [x_tenant_id]
        else:
            collections_to_search = [os.getenv("QDRANT_COLLECTION", "documents")]

        documents_map = {}

        for collection_name in collections_to_search:
            try:
                app_state.qdrant.get_collection(collection_name)

                scroll_result = app_state.qdrant.scroll(
                    collection_name=collection_name,
                    limit=10000,
                    with_payload=["filename", "source", "tenant_id"],
                    with_vectors=False
                )

                for point in scroll_result[0]:
                    payload = point.payload
                    filename = payload.get("filename")
                    if filename and filename not in documents_map:
                        source = payload.get("source", filename)
                        doc_type = "web" if (source and source.startswith("http")) or source == "web_scrape" else "file"

                        documents_map[filename] = {
                            "filename": filename,
                            "source": source,
                            "type": doc_type,
                            "collection": collection_name
                        }
            except Exception as e:
                logger.warning(f"Colección {collection_name} no encontrada o error: {e}")
                continue

        documents = sorted(documents_map.values(), key=lambda x: x["filename"])

        return {
            "total": len(documents),
            "documents": documents,
            "collections_searched": collections_to_search
        }
    except Exception as e:
        logger.error(f"Error listando documentos: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================
# ELIMINACIÓN
# ======================================================

@router.delete("/documents/delete", tags=["Documents"])
async def delete_document_endpoint(
    filename: str = Query(..., min_length=1),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
):
    """Elimina un documento de Qdrant y limpia su estado."""
    try:
        tenant_id = x_tenant_id or os.getenv("DEFAULT_TENANT_ID")
        collection_name = os.getenv("QDRANT_COLLECTION", "documents")

        logger.info(f"Solicitud de eliminación para: {filename}")

        from qdrant_client.models import Filter, FieldCondition, MatchValue

        must_conditions = [
            FieldCondition(key="filename", match=MatchValue(value=filename))
        ]
        if tenant_id:
            must_conditions.append(FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)))

        app_state.qdrant.delete(
            collection_name=collection_name,
            points_selector=Filter(must=must_conditions),
            wait=True
        )

        app_state.memory.delete_ingestion_status(filename)

        # Invalidar caché
        search_cache.invalidate_collection(collection_name)

        logger.info(f"✓ Documento eliminado: {filename}")
        return {"status": "deleted", "filename": filename}

    except Exception as e:
        logger.error(f"Error eliminando documento {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================
# ESTADO DE INGESTIÓN
# ======================================================

@router.post("/documents/status", tags=["Documents"])
async def update_document_status(
    payload: dict = Body(...),
):
    """
    Actualiza el estado de ingestión (usado por indexer o procesos externos)
    Payload: { "filename": "...", "status": "...", "message": "..." }
    """
    try:
        filename = payload.get("filename")
        status = payload.get("status")
        message = payload.get("message")

        if not filename or not status:
            raise HTTPException(status_code=400, detail="filename and status are required")

        app_state.memory.update_ingestion_status(filename, status, message)
        return {"status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error actualizando estado: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/ingestion-status", tags=["Documents"])
async def get_ingestion_status_endpoint(
    limit: int = 20,
):
    """Obtiene los últimos estados de ingestión"""
    try:
        return app_state.memory.get_ingestion_status(limit=limit)
    except Exception as e:
        logger.error(f"Error obteniendo status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/cleanup-old-status", tags=["Documents"])
async def cleanup_old_status_endpoint(
    days: int = 30,
):
    """
    Limpia estados de ingestión antiguos (mantenimiento).
    Por defecto borra estados de hace más de 30 días.
    """
    try:
        deleted = app_state.memory.cleanup_old_statuses(days=days)
        return {"status": "cleaned", "deleted": deleted}
    except Exception as e:
        logger.error(f"Error limpiando status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

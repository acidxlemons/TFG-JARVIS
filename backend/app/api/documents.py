"""
backend/app/api/documents.py

API para gestión de documentos (upload, delete, search)
Integra OCR + Chunking + Embeddings + Qdrant
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from typing import List, Optional
import tempfile
import os
from pathlib import Path

from app.processing.ocr.paddle_ocr import extract_text_from_pdf
from app.processing.chunking.smart_chunker import SmartChunker, validate_chunks
from app.processing.embeddings.sentence_transformer import get_embedder
from app.storage.qdrant_client import get_qdrant_client

router = APIRouter(prefix="/documents", tags=["documents"])


# ============================================
# MODELS
# ============================================

from pydantic import BaseModel

class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    total_pages: int
    total_chunks: int
    processing_time_ms: int
    needs_ocr: bool


class DocumentSearchQuery(BaseModel):
    query: str
    top_k: int = 5
    filter_by_filename: Optional[str] = None


# ============================================
# HELPERS
# ============================================

def _generate_doc_id(filename: str, content: bytes) -> str:
    """Genera ID único para documento"""
    import hashlib
    hash_val = hashlib.sha256(content).hexdigest()[:12]
    clean_name = Path(filename).stem.lower().replace(" ", "_")
    return f"{clean_name}_{hash_val}"


async def _process_and_index_pdf(
    file: UploadFile,
    metadata: dict,
) -> UploadResponse:
    """Pipeline completo: PDF → OCR → Chunks → Embeddings → Qdrant"""
    import time
    t0 = time.time()

    # 1. Guardar temporalmente
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        doc_id = _generate_doc_id(file.filename, content)

        # 2. Extraer texto (OCR o nativo)
        text, total_pages, needs_ocr = extract_text_from_pdf(tmp_path)
        
        if not text.strip():
            raise ValueError("No se pudo extraer texto del PDF")

        # 3. Chunking
        chunker = SmartChunker(chunk_size=500, overlap=50)
        chunks = chunker.chunk_text(
            text=text,
            source_filename=file.filename,
            preserve_pages=True,
        )

        if not chunks:
            raise ValueError("No se generaron chunks válidos")

        stats = validate_chunks(chunks)
        if stats.get("warnings"):
            print(f"⚠️  Chunking warnings: {stats['warnings']}")

        # 4. Embeddings
        embedder = get_embedder()
        texts = [c["text"] for c in chunks]
        vectors = embedder.encode_batch(texts)

        # 5. Insertar en Qdrant
        qdrant = get_qdrant_client()
        
        points = []
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
            point_id = f"{doc_id}_p{chunk['metadata'].get('page', 0)}_c{idx}"
            
            payload = {
                "text": chunk["text"],
                "filename": file.filename,
                "source": doc_id,
                "page": chunk["metadata"].get("page"),
                "chunk_index": idx,
                "from_ocr": needs_ocr,
                **metadata,
            }
            
            points.append({
                "id": point_id,
                "vector": vector,
                "payload": payload,
            })

        from qdrant_client.models import PointStruct
        qdrant.upsert(
            collection_name=os.getenv("QDRANT_COLLECTION", "documents"),
            points=[PointStruct(**p) for p in points],
            wait=True,
        )

        processing_time = int((time.time() - t0) * 1000)

        return UploadResponse(
            doc_id=doc_id,
            filename=file.filename,
            total_pages=total_pages,
            total_chunks=len(chunks),
            processing_time_ms=processing_time,
            needs_ocr=needs_ocr,
        )

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ============================================
# ENDPOINTS
# ============================================

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    department: Optional[str] = None,
    document_type: Optional[str] = None,
):
    """
    Sube y procesa un PDF.
    
    Pipeline:
    1. OCR (si es escaneado) o extracción nativa
    2. Chunking inteligente
    3. Embeddings (SentenceTransformer)
    4. Indexación en Qdrant
    """
    
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF")

    metadata = {}
    if department:
        metadata["department"] = department
    if document_type:
        metadata["document_type"] = document_type

    try:
        result = await _process_and_index_pdf(file, metadata)
        return result
    
    except Exception as e:
        raise HTTPException(500, f"Error procesando PDF: {str(e)}")


@router.post("/batch-upload")
async def batch_upload(
    files: List[UploadFile] = File(...),
    department: Optional[str] = None,
):
    """Procesa múltiples PDFs en batch"""
    
    results = []
    errors = []

    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            errors.append(f"{file.filename}: formato no soportado")
            continue

        try:
            metadata = {"department": department} if department else {}
            result = await _process_and_index_pdf(file, metadata)
            results.append(result.dict())
        
        except Exception as e:
            errors.append(f"{file.filename}: {str(e)}")

    return {
        "processed": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


@router.delete("/document/{doc_id}")
async def delete_document(doc_id: str):
    """Elimina un documento y todos sus chunks"""
    
    try:
        qdrant = get_qdrant_client()
        
        # Buscar puntos del documento
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        scroll_result = qdrant.scroll(
            collection_name=os.getenv("QDRANT_COLLECTION", "documents"),
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="source", match=MatchValue(value=doc_id))
                ]
            ),
            limit=10000,
            with_payload=False,
        )

        point_ids = [point.id for point in scroll_result[0]]
        
        if point_ids:
            qdrant.delete(
                collection_name=os.getenv("QDRANT_COLLECTION", "documents"),
                points_selector=point_ids,
                wait=True,
            )

        return {
            "status": "success",
            "doc_id": doc_id,
            "chunks_deleted": len(point_ids),
        }
    
    except Exception as e:
        raise HTTPException(500, f"Error eliminando documento: {str(e)}")


@router.post("/search")
async def search_documents(query: DocumentSearchQuery):
    """Búsqueda semántica en documentos indexados"""
    
    try:
        embedder = get_embedder()
        qdrant = get_qdrant_client()

        # Generar embedding de la query
        query_vector = embedder.encode([query.query])[0].tolist()

        # Buscar en Qdrant
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        search_filter = None
        if query.filter_by_filename:
            search_filter = Filter(
                must=[
                    FieldCondition(
                        key="filename",
                        match=MatchValue(value=query.filter_by_filename)
                    )
                ]
            )

        results = qdrant.search(
            collection_name=os.getenv("QDRANT_COLLECTION", "documents"),
            query_vector=query_vector,
            limit=query.top_k,
            query_filter=search_filter,
            with_payload=True,
        )

        return {
            "query": query.query,
            "total_results": len(results),
            "results": [
                {
                    "text": r.payload.get("text", "")[:200] + "...",
                    "score": r.score,
                    "filename": r.payload.get("filename"),
                    "page": r.payload.get("page"),
                    "source": r.payload.get("source"),
                }
                for r in results
            ],
        }
    
    except Exception as e:
        raise HTTPException(500, f"Error en búsqueda: {str(e)}")


@router.get("/stats")
async def get_stats():
    """Estadísticas de la colección de documentos"""
    
    try:
        qdrant = get_qdrant_client()
        collection = qdrant.get_collection(
            os.getenv("QDRANT_COLLECTION", "documents")
        )

        return {
            "collection_name": collection.config.params.name,
            "total_points": collection.points_count,
            "vector_dim": collection.config.params.vectors.size,
            "distance": collection.config.params.vectors.distance,
        }
    
    except Exception as e:
        raise HTTPException(500, f"Error obteniendo stats: {str(e)}")
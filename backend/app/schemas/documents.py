# backend/app/schemas/documents.py
"""
Esquemas Pydantic para los endpoints de gestión de documentos.

Incluye modelos para:
- Subida de documentos (upload)
- Búsqueda directa en documentos (sin agente)
- Listado de documentos indexados
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class DocumentUploadRequest(BaseModel):
    """
    Petición para subir un documento al sistema.

    El documento se envía codificado en base64 y se procesa en background:
    1. Decodificación base64 → archivo temporal
    2. Detección de formato y extracción de texto (OCR si es necesario)
    3. Chunking semántico (fragmentación inteligente)
    4. Generación de embeddings vectoriales
    5. Indexación en Qdrant (base de datos vectorial)

    Campos:
    - filename: Nombre del archivo (ej: "informe_calidad.pdf").
    - content_base64: Contenido del archivo codificado en base64.
    - metadata: Metadatos opcionales (departamento, tipo, etc.).
    """
    filename: str
    content_base64: str
    metadata: Optional[dict] = {}


class SearchRequest(BaseModel):
    """
    Petición de búsqueda directa en documentos.

    Realiza una búsqueda semántica sin pasar por el agente conversacional,
    útil para búsquedas programáticas o desde pipelines.

    Campos:
    - query: Texto de búsqueda.
    - top_k: Número de resultados a retornar (default: 5).
    - filter_by_filename: Filtrar por nombre de archivo específico.
    - exclude_ocr: Excluir resultados que provienen de OCR.
    """
    query: str
    top_k: int = 5
    filter_by_filename: Optional[str] = None
    exclude_ocr: bool = False


class DocumentList(BaseModel):
    """
    Respuesta del listado de documentos indexados.

    Campos:
    - total: Número total de documentos únicos.
    - documents: Lista de documentos con metadatos (filename, source, type, collection).
    - collections_searched: Colecciones de Qdrant que se buscaron.
    """
    total: int
    documents: List[dict]
    collections_searched: Optional[List[str]] = None

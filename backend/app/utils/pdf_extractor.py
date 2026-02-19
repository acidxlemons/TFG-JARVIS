# backend/app/utils/pdf_extractor.py
from __future__ import annotations
import io
from typing import Optional, Tuple, List

import fitz  # PyMuPDF
from paddleocr import PaddleOCR

# Reutiliza un OCR global para evitar recargas
_OCR_SINGLETON: Optional[PaddleOCR] = None

def get_ocr(lang: str = "en") -> PaddleOCR:
    global _OCR_SINGLETON
    if _OCR_SINGLETON is None:
        # Usa CPU por defecto, respeta tu variable de entorno OCR_USE_GPU si ya la tienes en tu app
        import os
        use_gpu = os.environ.get("OCR_USE_GPU", "false").lower() == "true"
        _OCR_SINGLETON = PaddleOCR(use_angle_cls=True, lang="latin", use_gpu=use_gpu)
    return _OCR_SINGLETON

def extract_text_pymupdf(pdf_bytes: bytes) -> str:
    """
    Extrae texto 'nativo' (no OCR) de un PDF usando PyMuPDF.
    """
    text_chunks: List[str] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            # "text" = extracción directa; si no hay texto real, esto suele salir vacío
            t = page.get_text("text") or ""
            if t.strip():
                text_chunks.append(t)
    return "\n".join(text_chunks).strip()

def pdf_page_images(pdf_bytes: bytes, dpi: int = 200) -> List[Tuple[int, bytes]]:
    """
    Renderiza cada página a imagen (PNG) para OCR.
    Devuelve lista de (page_index, png_bytes).
    """
    out: List[Tuple[int, bytes]] = []
    zoom = dpi / 72.0  # 72 dpi es base PDF
    mat = fitz.Matrix(zoom, zoom)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)  # RGB
            out.append((i, pix.tobytes("png")))
    return out

def ocr_pages(png_pages: List[Tuple[int, bytes]], lang: str = "latin") -> str:
    """
    Pasa OCR por cada imagen de página y concatena.
    """
    ocr = get_ocr(lang=lang)
    text_chunks: List[str] = []
    for idx, png_bytes in png_pages:
        # PaddleOCR espera ruta o np.ndarray; usamos bytes→np.array
        import numpy as np
        import cv2

        img_array = np.frombuffer(png_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        result = ocr.ocr(img, cls=True)
        # result es lista por bloques; concatenamos las líneas
        if result and result[0]:
            lines = [line[1][0] for line in result[0] if line and line[1]]
            if lines:
                text_chunks.append("\n".join(lines))
    return "\n\n".join(text_chunks).strip()

def extract_pdf_text_hybrid(pdf_bytes: bytes, min_chars_for_direct: int = 300) -> str:
    """
    1) Intenta extracción directa (PyMuPDF).
    2) Si es escaso, cae a OCR (PaddleOCR).
    """
    direct = extract_text_pymupdf(pdf_bytes)
    if len(direct) >= min_chars_for_direct:
        return direct

    # OCR fallback
    images = pdf_page_images(pdf_bytes, dpi=220)
    ocr_text = ocr_pages(images, lang="latin")
    # Si OCR también sale escaso, devolvemos lo que haya
    if len(ocr_text) > len(direct):
        return ocr_text
    return direct or ocr_text

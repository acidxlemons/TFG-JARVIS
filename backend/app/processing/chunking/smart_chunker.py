# backend/app/processing/chunking/smart_chunker.py
"""
Smart Chunker - Chunking semántico inteligente
Divide documentos respetando estructura y contexto.
"""

from __future__ import annotations

from typing import List, Dict, Optional, Tuple
import re
import logging
import hashlib

logger = logging.getLogger(__name__)


def _stable_id(*parts: str, maxlen: int = 12) -> str:
    """Crea un id corto estable a partir de varias partes."""
    h = hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()
    return h[:maxlen]


class SmartChunker:
    """
    Chunker inteligente que:
    - Respeta párrafos y secciones
    - Mantiene contexto (headers, títulos)
    - Divide por oraciones cuando es necesario
    - Añade overlap para continuidad
    - (Opcional) preserva numeración de páginas si están marcadas
    """

    # Separador de páginas robusto: línea que contenga exactamente "=== PÁGINA ==="
    PAGE_SPLIT_RE = re.compile(r"^\s*===\s*P[ÁA]GINA\s*===\s*$", re.MULTILINE)
    # División de párrafos: bloques separados por 1+ líneas en blanco
    PARAGRAPH_SPLIT_RE = re.compile(r"\n{2,}")
    # División de oraciones (heurística)
    SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\!\?])\s+")
    # Posibles encabezados / marcadores de sección
    SECTION_HEADER_RE = re.compile(r"^(#{1,6}\s+.+|[A-ZÁÉÍÓÚÑ][\w\s\-]{2,}:|\d+\.\s+.+)$", re.MULTILINE)

    def __init__(
        self,
        chunk_size: int = 500,
        overlap: int = 50,
        min_chunk_size: int = 100,
        max_chunk_size: Optional[int] = None,
        drop_tiny: bool = True,
    ):
        """
        Args:
            chunk_size: Tamaño objetivo del chunk en caracteres.
            overlap: Solapamiento (chars) entre chunks consecutivos (solo cuando se corta).
            min_chunk_size: Tamaño mínimo recomendado; se intentará fusionar trozos menores.
            max_chunk_size: Límite duro superior; si None, usa 1.5 * chunk_size.
            drop_tiny: Si True, descarta fragmentos ridículamente pequeños (< 30 chars).
        """
        self.chunk_size = max(64, int(chunk_size))
        self.overlap = max(0, int(overlap))
        self.min_chunk_size = max(1, int(min_chunk_size))
        self.max_chunk_size = int(max_chunk_size or (self.chunk_size * 1.5))
        self.drop_tiny = drop_tiny

        logger.info(
            f"SmartChunker: size={self.chunk_size}, overlap={self.overlap}, "
            f"min={self.min_chunk_size}, max={self.max_chunk_size}"
        )

    # --------------------------
    # API principal
    # --------------------------

    def chunk_text(
        self,
        text: str,
        source_filename: str,
        preserve_pages: bool = True,
    ) -> List[Dict]:
        """
        Divide texto en chunks inteligentes.

        Args:
            text: Texto completo a dividir.
            source_filename: Nombre del archivo fuente.
            preserve_pages: Mantener información de páginas si hay separadores.

        Returns:
            Lista de chunks con metadata.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            logger.warning(f"Texto vacío en {source_filename}")
            return []

        if preserve_pages and self._has_page_markers(cleaned):
            pages = self._split_pages(cleaned)
            chunks: List[Dict] = []
            for page_num, page_text in pages:
                if not page_text.strip():
                    continue
                chunks.extend(self._chunk_single_block(page_text, source_filename, page_num))
        else:
            chunks = self._chunk_single_block(cleaned, source_filename, None)

        # Fusionar fragmentos demasiado pequeños adyacentes
        chunks = self._merge_small_chunks(chunks)

        # Asignar índices e IDs estables
        for idx, ch in enumerate(chunks):
            ch["metadata"]["chunk_index"] = idx
            ch["id"] = _stable_id(source_filename, str(ch["metadata"].get("page")), str(idx))

        logger.info(f"Generados {len(chunks)} chunks de {source_filename}")
        return chunks

    # --------------------------
    # Internos
    # --------------------------

    def _has_page_markers(self, text: str) -> bool:
        return bool(self.PAGE_SPLIT_RE.search(text))

    def _split_pages(self, text: str) -> List[Tuple[int, str]]:
        """
        Divide por separadores de página. Considera texto previo al primer separador como página 1 si aplica.
        """
        parts = self.PAGE_SPLIT_RE.split(text)
        # Si el texto empieza con separador, parts[0] será "", lo manejamos igualmente.
        pages: List[Tuple[int, str]] = []
        page_counter = 1
        for block in parts:
            if block.strip():
                pages.append((page_counter, block.strip()))
                page_counter += 1
        return pages if pages else [(1, text.strip())]

    def _chunk_single_block(self, block_text: str, filename: str, page_num: Optional[int]) -> List[Dict]:
        """
        Divide un bloque (página o documento completo) en chunks <= max_chunk_size,
        intentando respetar párrafos y oraciones.
        """
        if len(block_text) <= self.max_chunk_size:
            return [self._make_chunk(block_text, filename, page_num)]

        paragraphs = [p.strip() for p in self.PARAGRAPH_SPLIT_RE.split(block_text) if p.strip()]
        chunks: List[Dict] = []
        buf = ""

        for para in paragraphs:
            # Caso: párrafo cabe en el buffer actual
            if len(buf) + len(para) + 2 <= self.chunk_size:
                buf = (buf + "\n\n" + para).strip() if buf else para
                continue

            # Caso: párrafo muy largo -> dividir por oraciones
            if len(para) > self.chunk_size:
                if buf:
                    # Emitimos el buffer como chunk y reseteamos
                    chunks.append(self._make_chunk(buf, filename, page_num))
                    buf = ""

                for sent_chunk in self._split_long_paragraph(para):
                    # Emitimos cada trozo del párrafo largo como chunk independiente
                    chunks.append(self._make_chunk(sent_chunk, filename, page_num))

                continue

            # Caso: el párrafo no cabe, cerramos el buffer actual y empezamos otro con overlap
            if buf:
                chunks.append(self._make_chunk(buf, filename, page_num))
                if self.overlap > 0:
                    overlap_text = buf[-self.overlap :]
                    buf = (overlap_text + "\n\n" + para).strip()
                else:
                    buf = para
            else:
                buf = para

        if buf:
            chunks.append(self._make_chunk(buf, filename, page_num))

        # Si alguno superó max_chunk_size por acumulación, lo re-spliteamos duramente
        normalized: List[Dict] = []
        for ch in chunks:
            if len(ch["text"]) <= self.max_chunk_size:
                normalized.append(ch)
            else:
                normalized.extend(self._force_split(ch, filename, page_num))

        return normalized

    def _split_long_paragraph(self, paragraph: str) -> List[str]:
        """
        Divide párrafo muy largo por oraciones (heurística) y, si una oración sigue siendo
        demasiado larga, fuerza split por palabras.
        """
        sentences = [s.strip() for s in self.SENTENCE_SPLIT_RE.split(paragraph) if s.strip()]
        if not sentences:
            # Fallback: split por palabras si el regex falló
            return self._force_word_split(paragraph, self.chunk_size)

        out: List[str] = []
        buf = ""
        for sent in sentences:
            if len(buf) + len(sent) + 1 <= self.chunk_size:
                buf = f"{buf} {sent}".strip() if buf else sent
            else:
                if buf:
                    out.append(buf.strip())
                if len(sent) > self.chunk_size:
                    out.extend(self._force_word_split(sent, self.chunk_size))
                    buf = ""
                else:
                    buf = sent
        if buf:
            out.append(buf.strip())
        return out

    def _force_word_split(self, text: str, size: int) -> List[str]:
        words = text.split()
        out: List[str] = []
        buf = ""
        for w in words:
            add = (w if not buf else " " + w)
            if len(buf) + len(add) <= size:
                buf += add
            else:
                if buf:
                    out.append(buf)
                buf = w
        if buf:
            out.append(buf)
        return out

    def _force_split(self, chunk: Dict, filename: str, page_num: Optional[int]) -> List[Dict]:
        """
        Split duro de un chunk que excede max_chunk_size.
        """
        text = chunk["text"]
        pieces: List[Dict] = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            sub = text[start:end]
            pieces.append(self._make_chunk(sub, filename, page_num))
            # Añadir overlap (si queda texto)
            if end < len(text) and self.overlap > 0:
                start = end - self.overlap
            else:
                start = end
        return pieces

    def _merge_small_chunks(self, chunks: List[Dict]) -> List[Dict]:
        """
        Fusiona chunks adyacentes cuando alguno queda por debajo de min_chunk_size.
        Respeta cambios de página.
        """
        if not chunks:
            return []

        merged: List[Dict] = []
        buf = None  # tipo Dict

        def _append_current():
            nonlocal buf
            if buf:
                if not self._is_tiny(buf["text"]) or not self.drop_tiny:
                    merged.append(buf)
                buf = None

        for ch in chunks:
            if buf is None:
                buf = ch
                continue

            # Si páginas distintas, empuja el buffer y resetea
            if buf["metadata"].get("page") != ch["metadata"].get("page"):
                _append_current()
                buf = ch
                continue

            # Si el actual es pequeño, intentamos fusionar
            if len(buf["text"]) < self.min_chunk_size or len(ch["text"]) < self.min_chunk_size:
                combined = (buf["text"].rstrip() + "\n\n" + ch["text"].lstrip()).strip()
                if len(combined) <= self.max_chunk_size:
                    buf = self._make_chunk(
                        combined, buf["metadata"]["filename"], buf["metadata"].get("page")
                    )
                else:
                    # No cabe fusionado: cerramos buf y seguimos
                    _append_current()
                    buf = ch
            else:
                _append_current()
                buf = ch

        _append_current()
        return merged

    def _is_tiny(self, s: str) -> bool:
        return len((s or "").strip()) < 30

    def _make_chunk(self, text: str, filename: str, page_num: Optional[int]) -> Dict:
        text_clean = text.strip()
        meta = {
            "source": filename,
            "filename": filename,
            "page": page_num,
            "char_count": len(text_clean),
        }

        # Añadimos hint de sección si existe cerca del inicio del chunk
        header = self._closest_header(text_clean)
        if header:
            meta["section"] = header

        return {"text": text_clean, "metadata": meta}

    def _closest_header(self, text: str) -> Optional[str]:
        """
        Intenta identificar un encabezado presente en las primeras ~300 chars del chunk.
        """
        head = text[:300]
        m = self.SECTION_HEADER_RE.search(head)
        if m:
            return m.group(0).strip()
        return None

    # --------------------------
    # Extensiones
    # --------------------------

    def chunk_with_context(
        self,
        text: str,
        filename: str,
        context_headers: Optional[List[str]] = None,
        preserve_pages: bool = True,
    ) -> List[Dict]:
        """
        Chunking que mantiene contexto de headers detectados externamente.
        """
        chunks = self.chunk_text(text, filename, preserve_pages=preserve_pages)
        if not context_headers:
            return chunks

        # Mapear el header anterior más cercano por posición en el texto original
        for ch in chunks:
            snippet = ch["text"][:80]
            pos = text.find(snippet)
            if pos == -1:
                continue
            prev = None
            for h in context_headers:
                hpos = text.find(h)
                if 0 <= hpos <= pos:
                    if prev is None or hpos > text.find(prev):
                        prev = h
            if prev:
                ch["metadata"]["section"] = prev
        return chunks


# ============================================
# CHUNKER ESPECIALIZADO PARA MARKDOWN
# ============================================

class MarkdownChunker(SmartChunker):
    """
    Chunker especializado para Markdown.
    Respeta estructura de headers (#, ##, ###).
    """

    MD_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    def chunk_text(self, text: str, filename: str, preserve_pages: bool = False) -> List[Dict]:
        # Detectar todos los headers (no se usa directamente, pero útil si quieres post-procesar)
        _ = self.MD_HEADER_RE.findall(text)

        chunks = super().chunk_text(text, filename, preserve_pages=preserve_pages)

        # Añadir contexto de headers (nivel + texto) al metadata del chunk
        for ch in chunks:
            chunk_text = ch["text"]
            # encuentra la posición aproximada del inicio del chunk en el documento
            start_idx = text.find(chunk_text[:50])
            if start_idx < 0:
                continue

            best_header_text = None
            best_header_level = None
            best_pos = -1

            for m in self.MD_HEADER_RE.finditer(text):
                pos = m.start()
                if pos <= start_idx and pos > best_pos:
                    best_pos = pos
                    hashes = m.group(1)   # p.ej. "###"
                    header_text = m.group(2).strip()
                    best_header_text = header_text
                    best_header_level = len(hashes)

            if best_header_text:
                ch["metadata"]["header"] = best_header_text
                ch["metadata"]["header_level"] = best_header_level

        return chunks


# ============================================
# UTILIDADES
# ============================================

def estimate_tokens(text: str) -> int:
    """
    Estima número de tokens (aprox. 1 token ≈ 4 caracteres).
    """
    return max(1, len(text) // 4)


def validate_chunks(chunks: List[Dict]) -> Dict:
    """
    Valida calidad de chunks generados y devuelve estadísticas.
    """
    if not chunks:
        return {"valid": False, "error": "No chunks generated"}

    sizes = [len(c["text"]) for c in chunks]
    stats = {
        "valid": True,
        "total_chunks": len(chunks),
        "avg_size": sum(sizes) / len(sizes),
        "min_size": min(sizes),
        "max_size": max(sizes),
        "total_chars": sum(sizes),
        "estimated_tokens": sum(estimate_tokens(c["text"]) for c in chunks),
    }

    warnings: List[str] = []
    if stats["min_size"] < 50:
        warnings.append(f"Chunks muy pequeños detectados (min: {stats['min_size']})")
    if stats["max_size"] > (stats["avg_size"] * 3):
        warnings.append("Alta varianza de tamaños; considera ajustar chunk_size/overlap")

    stats["warnings"] = warnings
    return stats


# ============================================
# EJEMPLO DE USO
# ============================================

if __name__ == "__main__":
    chunker = SmartChunker(chunk_size=500, overlap=50)

    sample = """
=== PÁGINA ===
Introducción al Contrato

Este documento establece los términos y condiciones del acuerdo entre las partes.

Cláusula 1: Objeto del Contrato
El presente contrato tiene por objeto la prestación de servicios de consultoría.

Cláusula 2: Duración
La duración del contrato será de 12 meses, comenzando el 1 de enero de 2024.

=== PÁGINA ===
Cláusula 3: Precio
El precio total del contrato es de 50,000 euros, pagaderos en cuotas mensuales.

Cláusula 4: Confidencialidad
Las partes se comprometen a mantener la confidencialidad de toda información intercambiada.
"""

    chs = chunker.chunk_text(sample, "contrato.pdf")
    print(f"Generados {len(chs)} chunks.")
    for i, ch in enumerate(chs[:5], 1):
        print(f"Chunk {i} (p.{ch['metadata']['page']}): {len(ch['text'])} chars → {ch['text'][:90]}...")
    print(validate_chunks(chs))

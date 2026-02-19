# backend/app/processing/ocr/paddle_ocr.py
"""
Pipeline de OCR con PaddleOCR
Procesamiento paralelo (GPU/CPU) para PDFs escaneados e imágenes.
Incluye:
- Caché en disco sensible a versión + parámetros (dpi/lang/preproc)
- Detección robusta de si un PDF necesita OCR (hasta 3 primeras páginas)
- Preprocesado opcional (binarización/deskew) si hay OpenCV
- Paralelización con Ray (fracción de GPU configurable)
"""

from __future__ import annotations

import os
import time
import ray
import hashlib
import pickle
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

try:
    from paddleocr import PaddleOCR
    HAS_PADDLE = True
except ImportError:
    PaddleOCR = None
    HAS_PADDLE = False
    logger.warning("PaddleOCR no encontrado. El OCR de imágenes no estará disponible.")

from pdf2image import convert_from_path
from PIL import Image, ImageOps
import numpy as np

_OCR_PIPELINE_VERSION = "1.2.1"  # bump al tocar lógica


@dataclass
class OCRResult:
    """Resultado del OCR de un documento"""
    text: str
    pages: int
    confidence: float  # Confianza promedio
    processing_time: float  # Segundos
    from_cache: bool
    metadata: Dict


class OCRCache:
    """
    Caché de resultados OCR en disco

    La clave de caché incluye:
    - ruta+stat (tam/mtime)
    - versión de pipeline
    - idioma, dpi, flags de preprocesado
    """

    def __init__(self, cache_dir: str = "./cache/ocr"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"OCR Cache: {self.cache_dir}")

    def _get_file_fingerprint(self, file_path: str) -> str:
        stat = os.stat(file_path)
        return f"{Path(file_path).resolve()}|{stat.st_size}|{stat.st_mtime}"

    def _cache_key(
        self,
        file_path: str,
        lang: str,
        dpi: int,
        preproc: bool,
        use_gpu: bool,
    ) -> str:
        base = f"{_OCR_PIPELINE_VERSION}|{self._get_file_fingerprint(file_path)}|{lang}|{dpi}|preproc={preproc}|gpu={use_gpu}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()

    def get(self, file_path: str, *, lang: str, dpi: int, preproc: bool, use_gpu: bool) -> Optional[OCRResult]:
        try:
            key = self._cache_key(file_path, lang, dpi, preproc, use_gpu)
            cache_file = self.cache_dir / f"{key}.pkl"
            if cache_file.exists():
                with open(cache_file, "rb") as f:
                    result: OCRResult = pickle.load(f)
                result.from_cache = True
                logger.info(f"✓ Cache hit: {Path(file_path).name}")
                return result
            return None
        except Exception as e:
            logger.warning(f"Error leyendo caché: {e}")
            return None

    def set(self, file_path: str, result: OCRResult, *, lang: str, dpi: int, preproc: bool, use_gpu: bool):
        try:
            key = self._cache_key(file_path, lang, dpi, preproc, use_gpu)
            cache_file = self.cache_dir / f"{key}.pkl"
            with open(cache_file, "wb") as f:
                pickle.dump(result, f)
            logger.debug(f"Cached: {Path(file_path).name}")
        except Exception as e:
            logger.warning(f"Error guardando caché: {e}")


def _maybe_preprocess(img: Image.Image, enable: bool) -> Image.Image:
    """
    Preprocesado suave: escala de grises + binarización Otsu + deskew si hay OpenCV.
    """
    if not enable:
        return img
    try:
        import cv2  # opcional
        arr = np.array(ImageOps.exif_transpose(img).convert("L"))
        # binarización Otsu
        _, th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # deskew
        coords = np.column_stack(np.where(th < 255))
        angle = 0.0
        if coords.size > 0:
            rect = cv2.minAreaRect(coords)
            angle = rect[-1]
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle
        (h, w) = th.shape[:2]
        M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        rotated = cv2.warpAffine(th, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return Image.fromarray(rotated)
    except Exception:
        # fallback: solo a escala de grises
        return ImageOps.exif_transpose(img).convert("L")


@ray.remote
class _OCRWorker:
    """
    Worker OCR con PaddleOCR.
    Configurable para GPU (num_gpus>0) o CPU (num_gpus=0).
    Soporta fallback automático a CPU si la inicialización con GPU falla.
    """

    def __init__(
        self,
        lang: str = "es",
        use_gpu: bool = True,
        worker_id: int = 0,
        rec_batch_num: int = 6,
    ):
        self.worker_id = worker_id
        self._gpu_enabled = bool(use_gpu)
        logger.info(f"Inicializando OCR Worker {worker_id} (GPU={use_gpu})...")
        self.ocr = None
        
        if not HAS_PADDLE:
            logger.warning(f"Worker {worker_id}: PaddleOCR no instalado. OCR desactivado.")
            return

        # Intento con GPU, fallback CPU si falla
        try:
            self.ocr = PaddleOCR(
                use_angle_cls=True,
                lang=lang,
                use_gpu=use_gpu,
                gpu_mem=500 if use_gpu else 0,
                show_log=False,
                enable_mkldnn=not use_gpu,  # mejoras CPU
                det_db_thresh=0.3,
                det_db_box_thresh=0.5,
                rec_batch_num=rec_batch_num,
            )
            logger.info(f"✓ OCR Worker {worker_id} listo (modo {'GPU' if use_gpu else 'CPU'})")
        except Exception as e:
            if use_gpu:
                logger.warning(f"Fallo inicializando PaddleOCR con GPU en worker {worker_id}: {e}. Reintentando en CPU…")
                try:
                    self.ocr = PaddleOCR(
                        use_angle_cls=True,
                        lang=lang,
                        use_gpu=False,
                        gpu_mem=0,
                        show_log=False,
                        enable_mkldnn=True,
                        det_db_thresh=0.3,
                        det_db_box_thresh=0.5,
                        rec_batch_num=rec_batch_num,
                    )
                    self._gpu_enabled = False
                    logger.info(f"✓ OCR Worker {worker_id} reiniciado en modo CPU")
                except Exception as e2:
                    logger.error(f"Error fatal inicializando PaddleOCR en worker {worker_id}: {e2}")
                    # No raise here to avoid crashing the worker completely if OCR is optional
                    self.ocr = None
            else:
                logger.error(f"Error fatal inicializando PaddleOCR en worker {worker_id}: {e}")
                self.ocr = None

    def process_image_np(self, image: np.ndarray) -> Tuple[str, float]:
        try:
            result = self.ocr.ocr(image, cls=True)
            if not result or not result[0]:
                return "", 0.0
            lines: List[str] = []
            confs: List[float] = []
            for line in result[0]:
                txt = line[1][0]
                cf = float(line[1][1] or 0.0)
                if txt:
                    lines.append(txt)
                    confs.append(cf)
            text = "\n".join(lines)
            avg_conf = (sum(confs) / len(confs)) if confs else 0.0
            return text, avg_conf
        except Exception as e:
            logger.error(f"Worker {self.worker_id} error: {e}")
            return "", 0.0

    def process_pdf_page(self, pdf_path: str, page_num: int, dpi: int = 200, preproc: bool = True) -> Tuple[str, float]:
        try:
            images = convert_from_path(
                pdf_path,
                dpi=dpi,
                first_page=page_num,
                last_page=page_num,
                fmt="jpeg",
                grayscale=False,  # preproc controla escala de grises
            )
            if not images:
                return "", 0.0
            img = _maybe_preprocess(images[0], enable=preproc)
            arr = np.array(img)
            return self.process_image_np(arr)
        except Exception as e:
            logger.error(f"Error procesando página {page_num}: {e}")
            return "", 0.0


class OCRPipeline:
    """
    Pipeline completo de OCR

    - Paralelización con Ray
    - GPU fraccional configurable (num_gpus_per_worker)
    - Caché sensible a parámetros
    - Detección robusta de OCR necesario
    """

    def __init__(
        self,
        num_workers: int = 6,
        use_gpu: bool = True,
        lang: str = "es",
        cache_dir: str = "./cache/ocr",
        num_gpus_per_worker: float = 0.125,  # 8 workers por GPU por defecto
        rec_batch_num: int = 6,
        enable_preprocess: bool = True,
    ):
        self.num_workers = max(1, int(num_workers))
        self.use_gpu = bool(use_gpu)
        self.lang = lang
        self.enable_preprocess = enable_preprocess
        self.rec_batch_num = rec_batch_num

        # Caché
        self.cache = OCRCache(cache_dir)

        # Ray (marcar si lo iniciamos nosotros)
        self._ray_initialized_here = False
        if not ray.is_initialized():
            # object_store_memory opcional; ignorar reinit para evitar warnings
            ray.init(ignore_reinit_error=True, include_dashboard=False)
            self._ray_initialized_here = True

        # Crear workers con requisitos de recursos
        logger.info(f"Creando {self.num_workers} OCR workers (GPU={self.use_gpu})...")
        self.workers = []
        for i in range(self.num_workers):
            options = {}
            if self.use_gpu:
                options["num_gpus"] = max(0.0, float(num_gpus_per_worker))
            else:
                options["num_gpus"] = 0

            worker = _OCRWorker.options(**options).remote(
                lang=self.lang,
                use_gpu=self.use_gpu,
                worker_id=i,
                rec_batch_num=self.rec_batch_num,
            )
            self.workers.append(worker)

        logger.info(f"✓ OCR Pipeline inicializado ({self.num_workers} workers)")

    # ---------------------------
    # Detección OCR necesario
    # ---------------------------
    def needs_ocr(self, file_path: str) -> bool:
        """
        Detecta si un archivo necesita OCR.

        Estrategia:
        - Imágenes: siempre True
        - PDF: intenta extraer texto de hasta 3 primeras páginas
               si < 150 chars acumulados => OCR
        """
        file_path = Path(file_path)
        ext = file_path.suffix.lower()

        if ext in [".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"]:
            return True

        if ext == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    total = 0
                    for page in pdf.pages[:3]:
                        txt = page.extract_text() or ""
                        total += len(txt.strip())
                        if total >= 150:
                            logger.info(f"{file_path.name} tiene texto nativo suficiente ({total} chars)")
                            return False
                logger.info(f"{file_path.name} necesita OCR (texto nativo insuficiente: {total} chars)")
                return True
            except Exception as e:
                logger.warning(f"No se pudo inspeccionar PDF (asumo OCR): {e}")
                return True

        # Otros formatos no soportados por OCR aquí
        return False

    # ---------------------------
    # Procesamiento principal
    # ---------------------------
    def process_file(
        self,
        file_path: str,
        dpi: int = 200,
        force: bool = False,
    ) -> OCRResult:
        """
        Procesa un archivo con OCR.

        Soporta: PDF, JPG, PNG, TIFF, BMP, WEBP
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

        # caché
        cached = None if force else self.cache.get(
            str(file_path),
            lang=self.lang,
            dpi=dpi,
            preproc=self.enable_preprocess,
            use_gpu=self.use_gpu
        )
        if cached:
            return cached

        logger.info(f"⏳ Procesando con OCR: {file_path.name}")
        t0 = time.perf_counter()

        ext = file_path.suffix.lower()
        if ext == ".pdf":
            result = self._process_pdf(str(file_path), dpi)
        elif ext in [".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"]:
            result = self._process_image(str(file_path))
        else:
            raise ValueError(f"Formato no soportado para OCR: {ext}")

        result.processing_time = time.perf_counter() - t0
        result.from_cache = False

        self.cache.set(
            str(file_path),
            result,
            lang=self.lang,
            dpi=dpi,
            preproc=self.enable_preprocess,
            use_gpu=self.use_gpu
        )
        logger.info(
            f"✓ OCR completado: {file_path.name} "
            f"({result.pages} págs en {result.processing_time:.1f}s, "
            f"confianza media: {result.confidence:.2%})"
        )
        return result

    def _process_pdf(self, pdf_path: str, dpi: int) -> OCRResult:
        """
        Procesa PDF completo con OCR paralelo (página a página).
        """
        from pdf2image import pdfinfo_from_path

        num_pages = 0
        try:
            info = pdfinfo_from_path(pdf_path)
            num_pages = int(info.get("Pages", 0)) or 0
        except Exception:
            pass

        if num_pages <= 0:
            # fallback: convertir todo y contar
            try:
                all_imgs = convert_from_path(pdf_path, dpi=dpi)
                num_pages = len(all_imgs)
            except Exception as e:
                logger.error(f"No se pudo determinar nº de páginas del PDF: {e}")
                num_pages = 0

        if num_pages <= 0:
            # sin páginas → resultado vacío
            return OCRResult(
                text="",
                pages=0,
                confidence=0.0,
                processing_time=0.0,
                from_cache=False,
                metadata={
                    "dpi": dpi,
                    "pages": 0,
                    "workers_used": 0,
                    "lang": self.lang,
                    "gpu": self.use_gpu,
                    "preprocess": self.enable_preprocess,
                    "version": _OCR_PIPELINE_VERSION,
                },
            )

        logger.info(f"PDF con {num_pages} páginas; distribuyendo entre {self.num_workers} workers")

        # Lanzar tareas
        futures: List[Tuple[int, ray.ObjectRef]] = []
        for page_num in range(1, num_pages + 1):
            worker = self.workers[(page_num - 1) % self.num_workers]
            fut = worker.process_pdf_page.remote(pdf_path, page_num, dpi, self.enable_preprocess)
            futures.append((page_num, fut))

        results: Dict[int, str] = {}
        confs: List[float] = []
        for page_num, fut in futures:
            text, conf = ray.get(fut)
            results[page_num] = (text or "").strip()
            confs.append(float(conf or 0.0))

        # Ensamblar en orden
        ordered_pages = [results.get(i, "") for i in range(1, num_pages + 1)]
        full_text = "\n\n=== PÁGINA ===\n\n".join(ordered_pages)
        avg_conf = (sum(confs) / len(confs)) if confs else 0.0

        return OCRResult(
            text=full_text,
            pages=num_pages,
            confidence=avg_conf,
            processing_time=0.0,
            from_cache=False,
            metadata={
                "dpi": dpi,
                "pages": num_pages,
                "workers_used": self.num_workers,
                "lang": self.lang,
                "gpu": self.use_gpu,
                "preprocess": self.enable_preprocess,
                "version": _OCR_PIPELINE_VERSION,
            },
        )

    def _process_image(self, image_path: str) -> OCRResult:
        """Procesa imagen única."""
        img = Image.open(image_path)
        img = _maybe_preprocess(img, enable=self.enable_preprocess)
        arr = np.array(img)

        # repartir arbitrariamente al primer worker (imágenes sueltas)
        worker = self.workers[0]
        text, confidence = ray.get(worker.process_image_np.remote(arr))

        return OCRResult(
            text=(text or "").strip(),
            pages=1,
            confidence=float(confidence or 0.0),
            processing_time=0.0,
            from_cache=False,
            metadata={
                "image_size": getattr(img, "size", None),
                "format": getattr(img, "format", None),
                "lang": self.lang,
                "gpu": self.use_gpu,
                "preprocess": self.enable_preprocess,
                "version": _OCR_PIPELINE_VERSION,
            },
        )

    def process_batch(self, file_paths: List[str], dpi: int = 200) -> Dict[str, Optional[OCRResult]]:
        """Procesa múltiples archivos en batch (útil para indexación inicial)."""
        out: Dict[str, Optional[OCRResult]] = {}
        logger.info(f"Procesando batch de {len(file_paths)} archivos")
        for fp in file_paths:
            try:
                out[fp] = self.process_file(fp, dpi=dpi)
            except Exception as e:
                logger.error(f"Error procesando {fp}: {e}")
                out[fp] = None
        return out

    def shutdown(self):
        """Cierra recursos de Ray solo si lo iniciamos aquí."""
        try:
            if self._ray_initialized_here and ray.is_initialized():
                ray.shutdown()
                logger.info("OCR Pipeline cerrado")
        except Exception:
            pass


# ============================================
# FUNCIÓN AUXILIAR: EXTRAER TEXTO SIN OCR
# ============================================

def extract_text_native(file_path: str) -> Optional[str]:
    """
    Extrae texto de PDFs que tienen texto nativo (no escaneados).
    Usa pdfplumber (más preciso que PyPDF2).
    """
    try:
        import pdfplumber
        texts: List[str] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    texts.append(t.strip())
        return "\n\n=== PÁGINA ===\n\n".join(texts) if texts else ""
    except Exception as e:
        logger.error(f"Error extrayendo texto nativo: {e}")
        return None


# ============================================
# EJEMPLO DE USO
# ============================================

if __name__ == "__main__":
    ocr = OCRPipeline(
        num_workers=6,
        use_gpu=True,
        lang="es",
        enable_preprocess=True,
    )
    try:
        result = ocr.process_file("documento_escaneado.pdf")
        print(f"Páginas: {result.pages}")
        print(f"Confianza: {result.confidence:.2%}")
        print(f"Tiempo: {result.processing_time:.1f}s")
        print(f"Desde caché: {result.from_cache}")
        print(f"\nTexto extraído:\n{result.text[:500]}...")
    finally:
        ocr.shutdown()

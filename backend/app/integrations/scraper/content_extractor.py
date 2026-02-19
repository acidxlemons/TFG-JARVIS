"""
Extractor de contenido limpio desde HTML/URL con múltiples estrategias
- trafilatura (primario)
- readability-lxml (fallback 1)
- BeautifulSoup (fallback 2)
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Dict
from html import unescape

import trafilatura
from trafilatura.settings import use_config

try:
    from readability import Document as ReadabilityDocument
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False
    logging.warning("readability-lxml no instalado. Fallback 1 deshabilitado.")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    logging.warning("beautifulsoup4 no instalado. Fallback 2 deshabilitado.")

logger = logging.getLogger(__name__)


class ContentExtractor:
    """
    Extractor de contenido web con múltiples estrategias de fallback.
    
    Orden de extracción:
    1. trafilatura - Mejor para artículos y contenido estructurado
    2. readability - Bueno para noticias y blogs
    3. BeautifulSoup - Fallback básico para cualquier HTML
    """
    
    def __init__(self):
        self.cfg = use_config()
        # Tiempo máximo de extracción de trafilatura
        self.cfg.set("DEFAULT", "EXTRACTION_TIMEOUT", "30")
        # Incluir más contenido
        self.cfg.set("DEFAULT", "MIN_OUTPUT_SIZE", "100")
        self.cfg.set("DEFAULT", "MIN_EXTRACTED_SIZE", "50")

    def extract_from_html(self, html: str, url: Optional[str] = None) -> Optional[Dict]:
        """
        Extrae contenido limpio de HTML usando múltiples estrategias.
        
        Returns:
            Dict con: title, author, date, description, content, word_count, extraction_method
            o None si no se pudo extraer.
        """
        if not html or len(html.strip()) < 100:
            logger.warning("HTML vacío o muy corto")
            return None
        
        # 1) Trafilatura primero (mejor calidad)
        result = self._extract_with_trafilatura(html, url)
        if result and len(result.get("content", "")) > 100:
            result["extraction_method"] = "trafilatura"
            return self._post_process(result)
        
        # 2) Fallback: readability
        if HAS_READABILITY:
            result = self._extract_with_readability(html)
            if result and len(result.get("content", "")) > 100:
                result["extraction_method"] = "readability"
                return self._post_process(result)
        
        # 3) Fallback: BeautifulSoup (extracción básica)
        if HAS_BS4:
            result = self._extract_with_beautifulsoup(html)
            if result and len(result.get("content", "")) > 50:
                result["extraction_method"] = "beautifulsoup"
                return self._post_process(result)
        
        logger.warning("Todos los métodos de extracción fallaron")
        return None
    
    def _extract_with_trafilatura(self, html: str, url: Optional[str]) -> Optional[Dict]:
        """Extracción con trafilatura (mejor calidad)."""
        try:
            extracted = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                include_links=True,
                include_images=False,
                include_formatting=False,
                no_fallback=False,
                url=url,
                config=self.cfg,
            )
            
            if not extracted:
                return None
            
            metadata = trafilatura.extract_metadata(html)
            
            return {
                "title": metadata.title if metadata else None,
                "author": metadata.author if metadata else None,
                "date": metadata.date if metadata else None,
                "description": metadata.description if metadata else None,
                "content": extracted,
            }
        except Exception as e:
            logger.debug(f"trafilatura falló: {e}")
            return None
    
    def _extract_with_readability(self, html: str) -> Optional[Dict]:
        """Extracción con readability-lxml."""
        try:
            from readability import Document
            doc = Document(html)
            title = doc.short_title()
            content_html = doc.summary(html_partial=True)
            
            # Convertir HTML a texto limpio
            text = trafilatura.html2txt(content_html)
            if not text or not text.strip():
                return None
            
            return {
                "title": title,
                "author": None,
                "date": None,
                "description": None,
                "content": text,
            }
        except Exception as e:
            logger.debug(f"readability falló: {e}")
            return None
    
    def _extract_with_beautifulsoup(self, html: str) -> Optional[Dict]:
        """Extracción básica con BeautifulSoup (último recurso)."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Eliminar elementos no deseados
            for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 
                                       'aside', 'iframe', 'noscript', 'form']):
                tag.decompose()
            
            # Eliminar elementos con clases típicas de boilerplate
            boilerplate_classes = ['nav', 'menu', 'sidebar', 'footer', 'header', 
                                   'ad', 'advertisement', 'social', 'share', 'comment']
            for cls in boilerplate_classes:
                for el in soup.find_all(class_=re.compile(cls, re.I)):
                    el.decompose()
            
            # Extraer título
            title = None
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.get_text(strip=True)
            if not title:
                h1 = soup.find('h1')
                if h1:
                    title = h1.get_text(strip=True)
            
            # Buscar contenido principal
            main_content = None
            for selector in ['article', 'main', '[role="main"]', '.content', '#content', '.post', '.article']:
                main_content = soup.select_one(selector)
                if main_content:
                    break
            
            if not main_content:
                main_content = soup.find('body') or soup
            
            # Extraer texto
            text = main_content.get_text(separator='\n', strip=True)
            
            return {
                "title": title,
                "author": None,
                "date": None,
                "description": None,
                "content": text,
            }
        except Exception as e:
            logger.debug(f"BeautifulSoup falló: {e}")
            return None
    
    def _post_process(self, result: Dict) -> Dict:
        """
        Post-procesa el contenido extraído:
        - Limpia espacios múltiples
        - Normaliza saltos de línea
        - Calcula estadísticas
        """
        content = result.get("content", "")
        
        # Decodificar entidades HTML
        content = unescape(content)
        
        # Normalizar espacios y saltos de línea
        content = re.sub(r'\n{3,}', '\n\n', content)  # Max 2 saltos de línea
        content = re.sub(r'[ \t]+', ' ', content)      # Espacios múltiples -> 1
        content = re.sub(r' +\n', '\n', content)       # Espacios antes de \n
        content = content.strip()
        
        # Eliminar líneas muy cortas que suelen ser ruido
        lines = content.split('\n')
        lines = [l for l in lines if len(l.strip()) > 3 or l.strip() == '']
        content = '\n'.join(lines)
        
        result["content"] = content
        result["word_count"] = len(content.split())
        result["char_count"] = len(content)
        
        return result

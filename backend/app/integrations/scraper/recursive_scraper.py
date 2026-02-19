from typing import Set, List, Dict, Optional
import logging
from urllib.parse import urlparse, urljoin
import aiohttp
from bs4 import BeautifulSoup
import asyncio

logger = logging.getLogger(__name__)

class RecursiveWebScraper:
    """
    Crawler simple que navega recursivamente un dominio para descubrir y extraer contenido.
    NO renderiza JS (usa aiohttp + BeautifulSoup) para velocidad en el descubrimiento.
    """
    
    def __init__(self, start_url: str, max_depth: int = 2, max_pages: int = 10):
        self.start_url = start_url
        self.max_depth = max_depth
        self.max_pages = max_pages
        
        self.base_domain = urlparse(start_url).netloc
        self.visited: Set[str] = set()
        self.results: List[Dict] = []
        
        # Headers para evitar bloqueos simples
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; EnterpriseRagBot/1.0; +http://your-internal-bot.com)'
        }

    async def crawl(self) -> List[Dict]:
        """Inicia el proceso de crawling desde la URL inicial."""
        self.visited.clear()
        self.results.clear()
        
        await self._visit(self.start_url, 0)
        return self.results

    async def _visit(self, url: str, depth: int):
        """Visita una URL individual, extrae contenido y sigue enlaces."""
        if depth > self.max_depth:
            return
        
        if len(self.visited) >= self.max_pages:
            return

        # Normalizar URL (quitar fragmentos, etc)
        url = url.split('#')[0]
        if url in self.visited:
            return
        
        self.visited.add(url)
        logger.info(f"🕸️ Crawling (d={depth}): {url}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, timeout=10) as response:
                    if response.status != 200:
                        logger.warning(f"⚠️ Status {response.status} al visitar {url}")
                        return
                    
                    if 'text/html' not in response.headers.get('Content-Type', ''):
                        logger.info(f"⏭️ Omitiendo no-HTML: {url}")
                        return

                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # 1. Extraer contenido útil de esta página
                    # Usamos una limpieza básica aquí, idealmente reusaríamos logic de 'scrape.py' 
                    # pero para mantenerlo ligero hacemos extracción directa.
                    title = soup.title.string.strip() if soup.title else "No Title"
                    
                    # Eliminar scripts y estilos para texto limpio
                    for script in soup(["script", "style", "nav", "footer", "header"]):
                        script.decompose()
                        
                    text = soup.get_text(separator='\n\n')
                    clean_text = "\n".join(
                        line.strip() for line in text.splitlines() if line.strip()
                    )

                    self.results.append({
                        "url": url,
                        "title": title,
                        "content": clean_text,
                        "author": None,
                        "date": None,
                        "scraped_at": None, # Se llenará al indexar
                        "extraction_method": "recursive_bs4"
                    })

                    # 2. Buscar enlaces para seguir (si no hemos llegado al tope)
                    if depth < self.max_depth and len(self.visited) < self.max_pages:
                        links = await self._extract_internal_links(soup, url)
                        
                        # Procesamiento de hijos en paralelo (limitado)
                        # Para no saturar, tomamos los primeros N enlaces nuevos
                        pending_tasks = []
                        for link in links:
                            if len(self.visited) + len(pending_tasks) >= self.max_pages:
                                break
                            if link not in self.visited:
                                pending_tasks.append(self._visit(link, depth + 1))
                        
                        if pending_tasks:
                            await asyncio.gather(*pending_tasks)

        except Exception as e:
            logger.error(f"❌ Error visitando {url}: {e}")

    async def _extract_internal_links(self, soup: BeautifulSoup, current_url: str) -> Set[str]:
        """Extrae enlaces que pertenecen al mismo dominio base."""
        links = set()
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            
            # Resolver URL absoluta
            absolute_url = urljoin(current_url, href)
            parsed = urlparse(absolute_url)
            
            # Solo mismo dominio y esquema http/https
            if parsed.netloc == self.base_domain and parsed.scheme in ['http', 'https']:
                links.add(absolute_url)
                
        return links

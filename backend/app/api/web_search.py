from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
import logging
import re
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)

class SearchResult(BaseModel):
    title: str
    link: str
    snippet: str
    source_type: str = "web"

class WebSearchResponse(BaseModel):
    query: str
    results: List[SearchResult]

# Keywords que indican que la query necesita información actualizada
CURRENT_EVENT_KEYWORDS = [
    "fichaje", "fichó", "ficha", "transferencia", "traspaso",
    "actual", "ahora", "hoy", "ayer", "reciente", "último", "última",
    "2024", "2025", "nuevo", "nueva", "precio", "cuesta",
    "resultado", "partido", "ganó", "perdió", "marcador",
    "noticia", "noticias", "última hora", "breaking",
    "current", "latest", "recent", "today", "yesterday", "now"
]

def needs_fresh_results(query: str) -> bool:
    """Detecta si la query necesita resultados frescos/recientes."""
    query_lower = query.lower()
    return any(kw in query_lower for kw in CURRENT_EVENT_KEYWORDS)


def extract_url_from_ddg_redirect(ddg_link: str) -> str:
    """Extrae la URL real de un enlace de redirección de DuckDuckGo."""
    try:
        if "duckduckgo.com/l/" in ddg_link:
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(ddg_link)
            query_params = parse_qs(parsed.query)
            if "uddg" in query_params:
                return query_params["uddg"][0]
    except Exception as e:
        logger.warning(f"Error extracting URL from DDG link: {e}")
    return ddg_link

async def search_with_html_scraping(query: str) -> List[SearchResult]:
    """Fallback: búsqueda usando HTML scraping de DuckDuckGo."""
    import httpx
    from bs4 import BeautifulSoup
    
    results = []
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query, "kl": "es-es"},  # Force region to Spain
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            )
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            for result_div in soup.find_all("div", class_="result", limit=5):
                try:
                    title_tag = result_div.find("a", class_="result__a")
                    if not title_tag:
                        continue
                    
                    title = title_tag.get_text(strip=True)
                    raw_link = title_tag.get("href", "")
                    
                    # Fix: Extract real URL from DDG redirect
                    link = extract_url_from_ddg_redirect(raw_link)
                    
                    snippet_tag = result_div.find("a", class_="result__snippet")
                    snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
                    
                    if title and link:
                        results.append(SearchResult(
                            title=title,
                            link=link,
                            snippet=snippet,
                            source_type="web"
                        ))
                except Exception as e:
                    logger.warning(f"Error parsing result: {e}")
                    continue
    except Exception as e:
        logger.warning(f"HTML scraping fallback failed: {e}")
    
    return results

@router.get("/web-search", response_model=WebSearchResponse)
async def web_search(q: str = Query(..., description="Query to search")):
    """
    Realiza una búsqueda en la web usando DuckDuckGo.
    Usa librería DDGS primero, fallback a HTML scraping si falla o no hay resultados.
    """
    logger.info(f"Web Search Query: {q}")
    try:
        results = []
        needs_news = needs_fresh_results(q)
        
        # Añadir año actual si parece necesitar info fresca
        current_year = datetime.now().year
        enhanced_query = q
        if needs_news and str(current_year) not in q:
            enhanced_query = f"{q} {current_year}"
            logger.info(f"Enhanced query with year: {enhanced_query}")
        

        # NOTA: La librería duckduckgo_search v8.1.1 estaba devolviendo resultados en chino (Baidu/Bing) erroneamente.
        # Hemos deshabilitado su uso en favor del scraping HTML directo que está verificado y funciona correctamente con la región es-es.
        
        logger.info(f"Using HTML scraping fallback for reliability (DDGS lib disabled)")
        results = await search_with_html_scraping(enhanced_query)
        
        # Validación extra: si el scraping falla o returns vacio, intentar query original sin año
        if not results and needs_news:
             logger.info(f"Retrying with original query without year")
             results = await search_with_html_scraping(q)

        
        logger.info(f"Found {len(results)} results for query: {q}")
        return WebSearchResponse(query=q, results=results)

    except Exception as e:
        logger.error(f"Error en web search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


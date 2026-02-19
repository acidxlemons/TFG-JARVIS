# backend/app/services/chat_service.py
"""
Servicio de Chat — Lógica de negocio para todas las modalidades de chat

Este módulo contiene la lógica de negocio del chat, separada del endpoint HTTP.
Maneja tres modos especiales y un modo por defecto:

MODOS:
1. SCRAPE: Cuando se detecta una URL en el mensaje.
   - Llama DIRECTAMENTE a las funciones del scraper (sin HTTP a localhost).
   - Scrapea la web con Playwright + fallback extractors.
   - Envía el contenido al LLM para que lo resuma.

2. WEB SEARCH: Cuando se detecta "busca en internet".
   - Llama DIRECTAMENTE a search_with_html_scraping() de web_search.py.
   - Formatea los resultados para el LLM.
   - El LLM sintetiza una respuesta con citas [1], [2], etc.

3. RAG: Cuando se detecta "busca en documentos".
   - Busca en todas las colecciones Qdrant autorizadas para el usuario.
   - Detecta documentos específicos mencionados en la query.
   - Construye contexto con los chunks más relevantes.

4. CHAT: Modo por defecto (conversación libre sin búsqueda).

CAMBIO IMPORTANTE vs main.py original:
    Antes: _handle_scrape_mode() y _handle_web_search_mode() hacían HTTP
           requests a localhost:8000 (el propio servidor), introduciendo latencia.
    Ahora: Se importan y llaman las funciones Python directamente, eliminando
           la latencia de red y el punto de fallo.
"""

import re
import os
import time
import logging
from typing import Optional, List, Tuple

from openai import OpenAI

from app.state import app_state, LITELLM_BASE_URL, LITELLM_API_KEY, LLM_MODEL
from app.metrics import rag_comparison_queries_total
from app.services.mode_detector import extract_document_names_from_query

logger = logging.getLogger(__name__)


# ======================================================
# CLIENTE LLM — Conexión con LiteLLM
# ======================================================

def get_llm_client() -> OpenAI:
    """
    Crea y devuelve un cliente OpenAI configurado para LiteLLM.

    LiteLLM actúa como proxy que traduce la API de OpenAI a múltiples
    proveedores de LLM (Ollama, Azure, OpenAI, Anthropic, etc.).
    """
    return OpenAI(
        base_url=f"{LITELLM_BASE_URL}/v1",
        api_key=LITELLM_API_KEY,
    )


# Instancia global del cliente LLM
llm_client = get_llm_client()


# ======================================================
# MODO SCRAPE — Scrapeo directo de URLs
# ======================================================

async def handle_scrape_mode(url: str, original_query: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Scrapea una URL y devuelve el contenido extraído.

    CAMBIO vs versión anterior:
    - Antes: Hacía HTTP POST a localhost:8000/scrape/analyze
    - Ahora: Importa y usa directamente las funciones del módulo scraper

    Flujo:
    1. Importa WebScraper del módulo de integraciones.
    2. Scrapea la URL con Playwright (headless Chrome).
    3. ContentExtractor prueba 3 estrategias: trafilatura → readability → BeautifulSoup.
    4. Retorna el contenido extraído, el título, y None si no hay error.

    Args:
        url: La URL a scrapear.
        original_query: La pregunta original del usuario (para contexto).

    Returns:
        Tupla (content, title, error_message):
        - Si éxito: (contenido_texto, titulo_pagina, None)
        - Si error: (None, None, "mensaje de error amigable")
    """
    logger.info(f"Modo scrape: obteniendo contenido de {url}")

    try:
        # Importar el scraper directamente (sin HTTP a localhost)
        from app.integrations.scraper.playwright_scraper import WebScraper

        scraper = WebScraper()
        result = await scraper.scrape(url)

        if not result or not result.get("content"):
            return (None, None, f"No pude extraer contenido de {url}.")

        content = result.get("content", "")
        title = result.get("title", url)

        if len(content) < 100:
            return (None, None, f"El contenido de {url} es muy corto o está vacío.")

        logger.info(f"Contenido extraído de {url}: {len(content)} caracteres")
        return (content, title, None)

    except Exception as e:
        if "timeout" in str(e).lower() or "Timeout" in type(e).__name__:
            logger.error(f"Timeout scrapeando {url}")
            return (None, None, f"La página {url} tardó demasiado en responder.")
        logger.error(f"Error en scrape de {url}: {e}")
        return (None, None, f"Error al acceder a {url}: {str(e)}")


# ======================================================
# MODO WEB SEARCH — Búsqueda en internet via DuckDuckGo
# ======================================================

async def handle_web_search_mode(query: str) -> Tuple[Optional[str], List[dict], Optional[str]]:
    """
    Realiza una búsqueda en internet y devuelve los resultados formateados.

    CAMBIO vs versión anterior:
    - Antes: Hacía HTTP GET a localhost:8000/web-search
    - Ahora: Importa y usa directamente search_with_html_scraping()

    Flujo:
    1. Limpia la query eliminando keywords de búsqueda ("busca en internet" etc.).
    2. Llama directamente a la función de búsqueda web (scraping de DuckDuckGo HTML).
    3. Formatea los resultados como texto estructurado para el LLM.

    Args:
        query: La query completa del usuario.

    Returns:
        Tupla (formatted_results, sources_list, error_message):
        - Si éxito: (texto_formateado, [fuentes], None)
        - Si error: (None, [], "mensaje de error")
    """
    # Limpiar la query eliminando keywords de búsqueda
    clean_query = re.sub(
        r'busca(r)?\s*(en\s*)?(el\s*)?internet|search\s*(the\s*)?web|search\s*online',
        '',
        query,
        flags=re.IGNORECASE
    ).strip()

    logger.info(f"Modo web search: buscando '{clean_query}'")

    try:
        # Importar la función de búsqueda directamente (sin HTTP a localhost)
        from app.api.web_search import search_with_html_scraping, needs_fresh_results
        from datetime import datetime

        # Mejorar query con año si necesita resultados frescos
        enhanced_query = clean_query
        needs_news = needs_fresh_results(clean_query)
        current_year = datetime.now().year

        if needs_news and str(current_year) not in clean_query:
            enhanced_query = f"{clean_query} {current_year}"
            logger.info(f"Enhanced query with year: {enhanced_query}")

        # Llamar directamente a la función de búsqueda
        search_results = await search_with_html_scraping(enhanced_query)

        # Retry sin año si no hay resultados
        if not search_results and needs_news:
            logger.info("Retrying with original query without year")
            search_results = await search_with_html_scraping(clean_query)

        if not search_results:
            return (None, [], f"No encontré resultados para '{clean_query}'.")

        # Formatear resultados para el LLM
        formatted = []
        sources = []
        for i, r in enumerate(search_results[:5], 1):
            formatted.append(
                f"[{i}] {r.title}\n{r.snippet}\nURL: {r.link}"
            )
            sources.append({
                "title": r.title,
                "url": r.link,
                "snippet": r.snippet
            })

        formatted_text = "\n\n".join(formatted)
        logger.info(f"Web search: {len(search_results)} resultados encontrados")
        return (formatted_text, sources, None)

    except Exception as e:
        logger.error(f"Error en web search: {e}")
        return (None, [], f"Error al buscar en internet: {str(e)}")


# ======================================================
# MODO RAG — Búsqueda en documentos corporativos
# ======================================================

def build_rag_context(
    clean_query: str,
    tenant_collections: List[str],
) -> Tuple[List[object], List[dict], str]:
    """
    Busca en las colecciones Qdrant autorizadas y construye contexto para el LLM.

    Flujo:
    1. Obtiene la lista de filenames indexados de todas las colecciones.
    2. Detecta si el usuario menciona documentos específicos (ej: "CR-277").
    3. Busca en cada colección autorizada.
    4. Combina resultados de forma justa (round-robin si hay múltiples colecciones).
    5. Formatea el contexto como texto legible para el LLM.

    Args:
        clean_query: La pregunta del usuario limpia (sin contexto de historial).
        tenant_collections: Lista de colecciones Qdrant donde buscar.

    Returns:
        Tupla (results, sources, context_text):
        - results: Los objetos RetrievalResult con los chunks recuperados.
        - sources: Lista de diccionarios con info de fuentes para la respuesta.
        - context_text: Texto formateado con los fragmentos relevantes.
    """
    results = []
    sources = []
    context_text = ""
    filter_filenames = None

    # 1) Obtener lista de documentos conocidos de TODAS las colecciones
    known_filenames = []
    try:
        for coll in tenant_collections:
            try:
                offset = None
                coll_filenames_set = set()
                while True:
                    scroll_result, next_page_offset = app_state.qdrant.scroll(
                        collection_name=coll,
                        limit=1000,
                        with_payload=["filename"],
                        offset=offset
                    )

                    for p in scroll_result:
                        fname = p.payload.get("filename")
                        if fname:
                            coll_filenames_set.add(fname)

                    if next_page_offset is None:
                        break
                    offset = next_page_offset

                known_filenames.extend(list(coll_filenames_set))
                logger.info(f"Retrieved {len(coll_filenames_set)} filenames from {coll}")

            except Exception as e:
                logger.warning(f"Error getting filenames from {coll}: {e}")

        known_filenames = list(set(known_filenames))
        logger.info(f"Found {len(known_filenames)} unique filenames across {len(tenant_collections)} collections")
    except Exception as e:
        logger.error(f"Error getting known filenames: {e}")
        known_filenames = []

    # 2) Detectar documentos mencionados en la query
    detected_docs = extract_document_names_from_query(clean_query, known_filenames)
    logger.info(
        f"DEBUG: CleanQuery='{clean_query[:50]}...', "
        f"known_filenames={known_filenames[:3] if known_filenames else []}, "
        f"detected_docs={detected_docs}"
    )

    if detected_docs:
        logger.info(f"Documentos detectados en query: {detected_docs}")
        filter_filenames = []
        for kf in known_filenames:
            for dd in detected_docs:
                if dd.upper() in kf.upper() or dd.lower() in kf.lower():
                    filter_filenames.append(kf)
                    break

        if filter_filenames:
            logger.info(f"Filtrando búsqueda a: {filter_filenames}")

    # 3) Detectar intención de comparación/listado para aumentar top_k
    comparison_keywords = [
        "compara", "compare", "diferencia", "difference", "disting", "vs", "versus",
        "lista", "listado", "list", "enumera", "enumerate", "relat", "relacion",
        "ventaja", "desventaja", "pros", "cons", "similitud", "similar",
        "cuales son", "qué son", "types of", "tipos de"
    ]

    is_comparison = any(kw in clean_query.lower() for kw in comparison_keywords)
    dynamic_top_k = 15 if is_comparison else 5

    if is_comparison:
        logger.info(f"Comparison/Listing intent detected. Increasing top_k to {dynamic_top_k}")
        rag_comparison_queries_total.inc()

    # 4) Buscar en todas las colecciones autorizadas
    all_results = []
    for collection in tenant_collections:
        try:
            effective_tenant = "" if collection in ["documents", "webs"] else collection

            collection_results = app_state.retriever.retrieve(
                query=clean_query,
                top_k=dynamic_top_k,
                filter_by_source=None,
                filter_by_filenames=filter_filenames if filter_filenames else None,
                exclude_ocr=False,
                tenant_id=effective_tenant,
                collection_name=collection,
            )
            logger.info(f"Collection '{collection}' returned {len(collection_results)} results")
            for r in collection_results:
                r.source_collection = collection
            all_results.extend(collection_results)
        except Exception as e:
            logger.warning(f"Error buscando en colección {collection}: {e}")

    # 5) Selección justa de resultados
    if filter_filenames:
        target_results = []
        other_results = []
        for r in all_results:
            if any(ff.lower() in r.filename.lower() or r.filename.lower() in ff.lower()
                   for ff in filter_filenames):
                target_results.append(r)
            else:
                other_results.append(r)

        target_results.sort(key=lambda x: x.score, reverse=True)
        other_results.sort(key=lambda x: x.score, reverse=True)

        if target_results:
            results = target_results[:dynamic_top_k]
            if len(results) < 3:
                results.extend(other_results[:3 - len(results)])
            logger.info(f"Documento específico detectado: {len(target_results)} resultados priorizados")
        else:
            all_results.sort(key=lambda x: x.score, reverse=True)
            results = all_results[:dynamic_top_k]

    elif len(tenant_collections) > 1:
        # Round-robin entre colecciones para balance justo
        results_by_collection = {}
        for r in all_results:
            coll = getattr(r, 'source_collection', 'unknown')
            if coll not in results_by_collection:
                results_by_collection[coll] = []
            results_by_collection[coll].append(r)

        for coll in results_by_collection:
            results_by_collection[coll].sort(key=lambda x: x.score, reverse=True)

        results = []
        max_per_collection = max(3, dynamic_top_k // len(tenant_collections) + 1)
        for coll in results_by_collection:
            results.extend(results_by_collection[coll][:max_per_collection])

        results.sort(key=lambda x: x.score, reverse=True)
        results = results[:dynamic_top_k]

        logger.info(f"Multi-collection final: {len(results)} results from {len(results_by_collection)} collections")
    else:
        all_results.sort(key=lambda x: x.score, reverse=True)
        results = all_results[:dynamic_top_k]

    # 6) Construir contexto legible para el LLM
    if results:
        context_blocks = []
        for r in results:
            context_blocks.append(
                f"[{r.filename} | score={r.score:.3f}]\n{r.text}"
            )
            sources.append({
                "filename": r.filename,
                "page": r.page,
                "citation": (r.citation or f"[{r.filename}]").replace("[[", "[").replace("]]", "]"),
                "score": r.score,
            })
        context_text = "\n\n---\n\n".join(context_blocks)

    return results, sources, context_text

# backend/app/services/mode_detector.py
"""
Detector Inteligente de Modo — Análisis automático de la intención del usuario

Este módulo analiza el mensaje del usuario para determinar qué modo de operación
debe usar el sistema, sin que el usuario tenga que especificarlo manualmente.

Modos detectados automáticamente:
1. SCRAPE: Si el mensaje contiene una URL → scrapear la web y resumir.
2. WEB SEARCH: Si contiene frases como "busca en internet" → buscar en DuckDuckGo.
3. RAG: Si contiene "busca en documentos" → buscar en Qdrant.
4. CHAT: Si no se detecta ninguno de los anteriores → conversación normal.

Prioridad de detección:
    URL detectada  →  SCRAPE (prioridad máxima)
    "busca en internet"  →  WEB SEARCH
    "busca en documentos"  →  RAG
    (ninguno)  →  CHAT (modo por defecto)

Funciones auxiliares:
- extract_clean_query(): Limpia el mensaje de contexto de conversación previo.
- extract_document_names_from_query(): Detecta códigos de documentos mencionados.
- is_related_to_history(): Determina si la pregunta sigue el hilo anterior.
"""

import re
import logging
from typing import Optional

from app.metrics import rag_filenames_detected_total, rag_comparison_queries_total

logger = logging.getLogger(__name__)


# ======================================================
# EXTRACCIÓN DE QUERY LIMPIA
# ======================================================

def extract_clean_query(message: str) -> str:
    """
    Extrae la query limpia de un mensaje que puede contener contexto de conversación.

    El pipeline de OpenWebUI puede enviar mensajes con formato:
        [PREVIOUS ANSWER - for context only, search with CURRENT QUESTION]
        ... respuesta anterior ...

        [CURRENT QUESTION - use this for document search]
        ... pregunta actual ...

    Esta función extrae SOLO la pregunta actual para la búsqueda RAG,
    ignorando el historial de conversación que puede estar incluido.

    Args:
        message: Mensaje completo del usuario (puede incluir contexto).

    Returns:
        La pregunta actual limpia, sin contexto de conversación.
    """
    # Buscar marcador de pregunta actual
    current_question_markers = [
        r"\[CURRENT QUESTION[^\]]*\]\s*",
        r"\[PREGUNTA ACTUAL[^\]]*\]\s*",
    ]

    for marker in current_question_markers:
        match = re.search(marker, message, re.IGNORECASE)
        if match:
            # Extraer todo después del marcador
            clean_query = message[match.end():].strip()
            logger.info(f"Extracted clean query: '{clean_query[:50]}...' from context-prefixed message")
            return clean_query

    # Si no hay marcador, devolver mensaje completo (sin prefijo de contexto si existe)
    context_markers = [
        r"^\[PREVIOUS ANSWER[^\]]*\].*?\[CURRENT QUESTION[^\]]*\]\s*",
        r"^\[CONVERSATION CONTEXT[^\]]*\].*?\[CURRENT QUESTION\]\s*",
    ]

    for marker in context_markers:
        match = re.match(marker, message, re.IGNORECASE | re.DOTALL)
        if match:
            clean_query = message[match.end():].strip()
            logger.info(f"Extracted clean query (fallback): '{clean_query[:50]}...'")
            return clean_query

    # Si no hay marcadores explícitos de sistema, intentar detectar formato de chat raw
    # Buscamos el último mensaje del usuario
    chat_patterns = [
        r"(?:^|\n)(?:User|Usuario|Human|Humano):\s*",
    ]

    last_user_index = -1
    used_pattern_len = 0

    for pattern in chat_patterns:
        matches = list(re.finditer(pattern, message, re.IGNORECASE))
        if matches:
            last_match = matches[-1]
            if last_match.start() > last_user_index:
                last_user_index = last_match.start()
                used_pattern_len = last_match.end() - last_match.start()

    if last_user_index != -1:
        candidate = message[last_user_index + used_pattern_len:].strip()
        logger.info(f"Extracted query from chat log pattern: '{candidate[:50]}...'")
        return candidate

    # Sin marcadores, devolver mensaje original
    return message


# ======================================================
# DETECCIÓN DE DOCUMENTOS EN LA QUERY
# ======================================================

def extract_document_names_from_query(query: str, known_filenames: list = None) -> list:
    """
    Detecta nombres de documentos mencionados en la query del usuario.

    Utiliza dos estrategias:
    1. Detección por patrón (regex): Busca códigos como CR-277, MAP-003, ISO9001.
    2. Match fuzzy con filenames conocidos: Si no hay código explícito, compara
       con la lista de documentos indexados en Qdrant.

    Ejemplos:
        "mira en el documento CR-277" → ["CR-277"]
        "resume UTAS-ITC-FRM-0601"   → ["UTAS-ITC-FRM-0601"]
        "compara MAP-003 y CR-277"   → ["MAP-003", "CR-277"]

    Args:
        query: La pregunta del usuario.
        known_filenames: Lista de filenames actualmente indexados en Qdrant.

    Returns:
        Lista de nombres/códigos de documentos detectados.
    """
    import unicodedata

    detected = []
    query_upper = query.upper()

    # Patrones comunes de códigos de documentos
    code_patterns = [
        r'\b([A-Z]{2,5}[-_]?\d{2,4})\b',   # CR-277, MAP003, FORM-027
        r'\b([A-Z]+\d{3,})\b',               # ISO9001, etc.
        r'\b(UTAS[-_][A-Z0-9\-_]+)\b',        # UTAS-ITC-FRM-0601 etc.
    ]

    for pattern in code_patterns:
        matches = re.findall(pattern, query_upper)
        for match in matches:
            detected.append(match)

    def normalize_text(text):
        """Elimina tildes y normaliza a minúsculas para comparación."""
        return ''.join(c for c in unicodedata.normalize('NFD', text.lower())
                       if unicodedata.category(c) != 'Mn')

    # Si hemos detectado códigos explícitos, devolvemos solo esos
    if detected:
        logger.info(f"Explicit document codes detected: {detected}. Skipping fuzzy search.")
        return list(set(detected))

    # Si NO hay códigos explícitos, usamos match fuzzy con filenames conocidos
    if known_filenames:
        query_norm = normalize_text(query)
        scored_matches = []

        for filename in known_filenames:
            filename_norm = normalize_text(filename)
            filename_no_ext_norm = filename_norm.rsplit('.', 1)[0]
            score = 0

            # 1) Match fuerte: partes significativas del nombre del archivo
            if len(filename_no_ext_norm) > 10:
                parts = re.split(r'[-_\s\.]', filename_no_ext_norm)
                significant_parts = [p for p in parts if len(p) >= 3]

                if len(significant_parts) >= 2:
                    matches_found = sum(1 for p in significant_parts if p in query_norm)
                    if matches_found >= 2:
                        score = matches_found
                        scored_matches.append((filename, score))
                        continue

            # 2) Match débil: coincidencia parcial única
            parts = re.split(r'[\s\-_\.]', filename_norm)
            for part in parts:
                if len(part) >= 4 and part in query_norm:
                    score = 0.5
                    scored_matches.append((filename, score))
                    break

        # Seleccionar ganadores
        if scored_matches:
            scored_matches.sort(key=lambda x: x[1], reverse=True)
            max_score = scored_matches[0][1]

            logger.info(f"Doc detection winner: '{scored_matches[0][0]}' (score={max_score})")

            if max_score >= 1.5:
                strong_matches = [m for m in scored_matches if m[1] >= 2]
                if strong_matches:
                    detected.extend([m[0] for m in strong_matches])
                    if len(strong_matches) > 1:
                        rag_comparison_queries_total.inc()
                else:
                    detected.extend([m[0] for m in scored_matches if m[1] >= max_score - 1])
            else:
                detected.extend([m[0] for m in scored_matches])

    final_detected = list(set(detected))

    # METRIC: Registrar detección
    if final_detected:
        rag_filenames_detected_total.labels(status="found", count=str(len(final_detected))).inc()
    else:
        rag_filenames_detected_total.labels(status="none", count="0").inc()

    return final_detected


# ======================================================
# DETECCIÓN DE MODO INTELIGENTE
# ======================================================

def detect_url_in_query(query: str) -> Optional[str]:
    """
    Detecta si hay una URL en la query del usuario.

    Args:
        query: Texto de la pregunta del usuario.

    Returns:
        La primera URL encontrada, o None si no hay ninguna.
    """
    url_pattern = r'https?://[^\s<>"\']+[^\s<>"\'.,;:!?\)\]]'
    matches = re.findall(url_pattern, query)
    if matches:
        logger.info(f"URL detectada en query: {matches[0]}")
        return matches[0]
    return None


def wants_web_search(query: str) -> bool:
    """
    Detecta si el usuario quiere una búsqueda en internet.

    Busca frases clave como "busca en internet", "search online", etc.

    Args:
        query: Texto de la pregunta del usuario.

    Returns:
        True si se detecta intención de búsqueda web, False en caso contrario.
    """
    web_search_keywords = [
        "busca en internet",
        "buscar en internet",
        "search the web",
        "search online",
        "buscar online",
        "busca online",
    ]
    query_lower = query.lower()
    for kw in web_search_keywords:
        if kw in query_lower:
            logger.info(f"Keyword de búsqueda web detectado: '{kw}'")
            return True
    return False


def wants_rag_search(query: str) -> bool:
    """
    Detecta si el usuario quiere buscar en los documentos RAG explícitamente.

    Solo activa RAG cuando el usuario lo pide directamente.
    Si también se detecta intención de búsqueda web, se da prioridad a la web.

    Args:
        query: Texto de la pregunta del usuario.

    Returns:
        True si se detecta intención de búsqueda RAG, False en caso contrario.
    """
    rag_keywords = [
        "busca en tus documentos",
        "busca en los documentos",
        "busca en mis documentos",
        "buscar en documentos",
        "busca en las paginas guardadas",
        "busca en las páginas guardadas",
        "busca en el rag",
        "busca en rag",
        "search in documents",
        "search documents",
        "search in rag",
        "busca en ",  # Generic "busca en X" without "internet"
    ]
    query_lower = query.lower()

    # Primero verificar que NO sea búsqueda en internet
    if wants_web_search(query):
        return False

    for kw in rag_keywords:
        if kw in query_lower:
            logger.info(f"Keyword de búsqueda RAG detectado: '{kw}'")
            return True
    return False


def is_related_to_history(current_query: str, previous_query: str) -> bool:
    """
    Determina si la pregunta actual está relacionada con el tema anterior.

    Usa una heurística de solapamiento de palabras significativas (4+ caracteres),
    excluyendo stopwords comunes en español e inglés.

    Args:
        current_query: La pregunta actual del usuario.
        previous_query: La pregunta anterior en la conversación.

    Returns:
        True si hay al menos 1 palabra significativa en común.
    """
    if not previous_query:
        return False

    current_words = set(re.findall(r'\w{4,}', current_query.lower()))
    previous_words = set(re.findall(r'\w{4,}', previous_query.lower()))

    stopwords = {
        'como', 'cual', 'cuales', 'donde', 'cuando', 'porque', 'para', 'sobre',
        'this', 'that', 'what', 'where', 'when', 'which', 'could', 'would',
        'esta', 'esto', 'esos', 'esas', 'ahora', 'antes', 'despues',
    }
    current_words -= stopwords
    previous_words -= stopwords

    overlap = current_words & previous_words

    is_related = len(overlap) >= 1

    if is_related:
        logger.info(f"Query relacionada con historial (overlap: {overlap})")
    else:
        logger.info(f"Query NO relacionada con historial (overlap insuficiente: {overlap})")

    return is_related

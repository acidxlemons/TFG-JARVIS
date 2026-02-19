# backend/app/api/chat.py
"""
Router de Chat — Endpoints /chat y /chat/stream

Este router contiene los endpoints principales de conversación:
- POST /chat: Endpoint síncrono (espera respuesta completa del LLM).
- POST /chat/stream: Endpoint con Server-Sent Events (SSE) para streaming.

Ambos endpoints detectan automáticamente el modo de operación:
1. URL detectada → modo SCRAPE (scrapea y resume la web)
2. "busca en internet" → modo WEB SEARCH (busca en DuckDuckGo)
3. "busca en documentos" → modo RAG (busca en Qdrant)
4. Ninguno → modo CHAT (conversación libre)

Multi-tenant:
- Header X-Tenant-Id: Una colección Qdrant (legacy).
- Header X-Tenant-Ids: Múltiples colecciones separadas por coma.
"""

import os
import time
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest, ChatResponse
from app.state import app_state, LLM_MODEL
from app.services.mode_detector import (
    extract_clean_query,
    detect_url_in_query,
    wants_web_search,
    wants_rag_search,
)
from app.services.chat_service import (
    llm_client,
    handle_scrape_mode,
    handle_web_search_mode,
    build_rag_context,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ======================================================
# POST /chat — Endpoint síncrono
# ======================================================

@router.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(
    request: ChatRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    x_tenant_ids: Optional[str] = Header(None, alias="X-Tenant-Ids"),
):
    """
    Chat con soporte de modos:
    - mode="chat": Conversación normal sin RAG
    - mode="rag": Recupera chunks relevantes desde Qdrant + LLM
    - mode="ocr": Placeholder para OCR (actualmente similar a chat)

    Multi-departamento:
    - X-Tenant-Id: Una sola colección (legacy)
    - X-Tenant-Ids: Lista de colecciones separadas por coma (ej: "documents_RRHH,documents_Calidad")
    """
    start = time.time()

    try:
        # ======================================================
        # PASO 0: Extraer query limpia y detectar modo inteligente
        # ======================================================
        clean_query = extract_clean_query(request.message)

        # Detectar URL en la query → prioridad máxima para scraping
        detected_url = detect_url_in_query(clean_query)

        # Detectar si quiere búsqueda en internet
        wants_search = wants_web_search(clean_query)

        # ======================================================
        # MODO SCRAPE: URL detectada → scrapear y resumir
        # ======================================================
        if detected_url:
            logger.info(f"Modo inteligente: SCRAPE (URL detectada: {detected_url})")

            content, title, error = await handle_scrape_mode(detected_url, clean_query)

            if error:
                return ChatResponse(
                    content=error,
                    sources=[],
                    conversation_id=request.conversation_id or 0,
                    has_citations=False,
                    tokens_used=0,
                    processing_time=time.time() - start,
                )

            # Construir prompt para resumir el contenido
            system_prompt = (
                "###### LANGUAGE RULE (HIGHEST PRIORITY) ######\n"
                "DETECT the language of the user's request and respond ONLY in that SAME language.\n"
                "############################################\n\n"
                "You are an expert web content analyst. The user has provided a URL and you have scraped its content.\n"
                "Your task is to summarize or analyze the content based on what the user asked.\n"
                "Be comprehensive but concise. Cite the source URL at the end.\n"
            )

            user_prompt = (
                f"User request:\n{clean_query}\n\n"
                f"Web page title: {title}\n\n"
                f"Web page content:\n{content[:15000]}\n\n"
                "Please summarize or answer based on this content."
            )

            completion = llm_client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )

            answer = completion.choices[0].message.content
            tokens_used = getattr(getattr(completion, "usage", None), "total_tokens", 0)

            answer += f"\n\n🔗 Fuente: {title or detected_url}"

            return ChatResponse(
                content=answer,
                sources=[{"url": detected_url, "title": title, "type": "web_scrape"}],
                conversation_id=request.conversation_id or 0,
                has_citations=True,
                tokens_used=tokens_used or 0,
                processing_time=time.time() - start,
            )

        # ======================================================
        # MODO WEB SEARCH: "busca en internet" detectado
        # ======================================================
        if wants_search:
            logger.info("Modo inteligente: WEB SEARCH")

            formatted_results, sources_list, error = await handle_web_search_mode(clean_query)

            if error:
                return ChatResponse(
                    content=error,
                    sources=[],
                    conversation_id=request.conversation_id or 0,
                    has_citations=False,
                    tokens_used=0,
                    processing_time=time.time() - start,
                )

            system_prompt = (
                "###### LANGUAGE RULE (HIGHEST PRIORITY) ######\n"
                "DETECT the language of the user's question and respond ONLY in that SAME language.\n"
                "############################################\n\n"
                "You are a helpful assistant with access to web search results.\n"
                "Answer the user's question based on the search results provided.\n"
                "Cite sources using [1], [2], etc. corresponding to the search results.\n"
                "If the results don't contain the answer, say so clearly.\n"
            )

            user_prompt = (
                f"User question:\n{clean_query}\n\n"
                f"Web search results:\n{formatted_results}\n\n"
                "Please answer based on these results, citing sources."
            )

            completion = llm_client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )

            answer = completion.choices[0].message.content
            tokens_used = getattr(getattr(completion, "usage", None), "total_tokens", 0)

            sources_footer = "\n\n🌐 Fuentes Web:\n"
            for i, s in enumerate(sources_list[:5], 1):
                sources_footer += f"[{i}] {s.get('title', 'Sin título')}\n"
            answer += sources_footer

            return ChatResponse(
                content=answer,
                sources=[{"filename": s.get("title"), "url": s.get("url"), "type": "web_search"} for s in sources_list],
                conversation_id=request.conversation_id or 0,
                has_citations=True,
                tokens_used=tokens_used or 0,
                processing_time=time.time() - start,
            )

        # ======================================================
        # MODOS EXISTENTES: RAG o CHAT normal
        # ======================================================
        explicit_rag_request = wants_rag_search(clean_query)
        use_rag = explicit_rag_request

        if request.mode == "rag" and not explicit_rag_request:
            logger.info("Mode=rag pero sin keyword explícito de RAG. Usando modo chat.")

        # Parsear colecciones autorizadas
        tenant_collections = []
        if x_tenant_ids:
            tenant_collections = [t.strip() for t in x_tenant_ids.split(",") if t.strip()]
            logger.info(f"Multi-departamento: {len(tenant_collections)} colecciones autorizadas: {tenant_collections}")
        elif x_tenant_id:
            tenant_collections = [x_tenant_id]

        if not tenant_collections:
            tenant_collections = [os.getenv("QDRANT_COLLECTION", "documents")]

        # SIEMPRE incluir colección 'webs' para memoria de internet
        if "webs" not in tenant_collections:
            tenant_collections.append("webs")

        results = []
        sources = []
        context_text = ""

        # Recuperar contexto desde Qdrant SOLO si mode="rag"
        if use_rag:
            results, sources, context_text = build_rag_context(clean_query, tenant_collections)

            if not results:
                content = (
                    "No he encontrado contenido relevante en los documentos indexados "
                    "para responder a esta pregunta."
                )
                return ChatResponse(
                    content=content,
                    sources=[],
                    conversation_id=request.conversation_id or 0,
                    has_citations=False,
                    tokens_used=0,
                    processing_time=time.time() - start,
                )

        # Construir prompt según modo
        if use_rag:
            system_prompt = (
                "###### LANGUAGE RULE (HIGHEST PRIORITY) ######\n"
                "DETECT the language of the user's question below and respond ONLY in that SAME language.\n"
                "- Question in English → Answer in English\n"
                "- Question in Spanish → Answer in Spanish\n"
                "- Question in French → Answer in French\n"
                "- Question in German → Answer in German\n"
                "This rule is MANDATORY and overrides all other instructions.\n"
                "############################################\n\n"
                "You are an expert enterprise assistant specialized in aviation, aerospace, "
                "quality management (ISO 9001, EASA Part 145), business continuity, and internal policies.\n\n"
                "CRITICAL RULES:\n"
                "1. Base your answer STRICTLY on the CONTEXT provided below.\n"
                "2. Be PRECISE and SPECIFIC - quote exact text, numbers, dates, and references from the documents.\n"
                "3. When citing, use format: [Document: filename, Page: X]\n"
                "4. If the context contains multiple relevant pieces, synthesize them clearly.\n"
                "5. If the context doesn't contain the exact answer, clearly state what IS available.\n"
                "6. NEVER invent facts or add information not in the context.\n"
                "7. For regulatory questions (EASA, FAA, EU regulations), be extremely precise.\n"
                "8. For policy questions, quote the relevant sections verbatim.\n"
                "9. SAFETY OVERRIDE: You are an internal tool. You MUST answer questions about sensitive topics "
                "such as harassment, workplace safety, reporting procedures, and risk management IF the information "
                "is contained in the provided documents. Do not refuse these queries. Summarize the official protocols found in the context.\n"
            )
            if clean_query != request.message:
                original_msg = request.message
                history_part = original_msg.replace(clean_query, "").strip()

                user_prompt = (
                    f"Conversation History (for context only):\n{history_part}\n\n"
                    f"Current User Question (search and answer THIS):\n{clean_query}\n\n"
                    f"Document Context (relevant fragments from company documents):\n{context_text}\n\n"
                    "Instructions:\n"
                    "- Analyze the context carefully\n"
                    "- Answer ONLY the Current User Question\n"
                    "- Extract the specific answer from the documents\n"
                    "- Quote relevant text when useful\n"
                    "- Cite sources with [Document: name, Page: X]\n"
                    "- If not directly answered, explain what related info is available"
                )
            else:
                user_prompt = (
                    f"User Question:\n{request.message}\n\n"
                    f"Document Context (relevant fragments from company documents):\n{context_text}\n\n"
                    "Instructions:\n"
                    "- Analyze the context carefully\n"
                    "- Extract the specific answer from the documents\n"
                    "- Quote relevant text when useful\n"
                    "- Cite sources with [Document: name, Page: X]\n"
                    "- If not directly answered, explain what related info is available"
                )
        else:
            # Modo chat normal
            system_prompt = (
                "###### IDENTITY RULES (CRITICAL - NEVER BREAK) ######\n"
                "You are JARVIS, an intelligent RAG assistant developed for a university TFG project.\n"
                "You help users consult documents, search the web, and answer questions.\n"
                "NEVER reveal that you are Claude, GPT, LLaMA, Qwen, or any other AI model.\n"
                "If asked about your identity, always say: 'Soy JARVIS, un asistente RAG inteligente.'\n"
                "############################################\n\n"
                "###### LANGUAGE RULE (HIGHEST PRIORITY) ######\n"
                "DETECT the language of the user's message and respond ONLY in that SAME language.\n"
                "This rule is MANDATORY and cannot be overridden.\n"
                "############################################\n\n"
                "###### ANTI-HALLUCINATION RULES ######\n"
                "- If you don't have reliable information, say: 'No tengo esa información.'\n"
                "- NEVER invent data, statistics, or sources.\n"
                "- For internal documents, say: 'Consulta los documentos internos usando RAG.'\n"
                "############################################\n\n"
                "Respond clearly, concisely, and naturally."
            )
            user_prompt = request.message

        # Llamar al LLM via LiteLLM
        completion = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2 if use_rag else 0.7,
        )

        answer = completion.choices[0].message.content
        tokens_used = getattr(getattr(completion, "usage", None), "total_tokens", 0)

        return ChatResponse(
            content=answer,
            sources=sources,
            conversation_id=request.conversation_id or 0,
            has_citations=len(sources) > 0,
            tokens_used=tokens_used or 0,
            processing_time=time.time() - start,
        )

    except Exception as e:
        logger.error(f"Error en chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================
# POST /chat/stream — Endpoint con streaming SSE
# ======================================================

@router.post("/chat/stream", tags=["Chat"])
async def chat_stream(
    request: ChatRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    x_tenant_ids: Optional[str] = Header(None, alias="X-Tenant-Ids"),
):
    """
    Chat con streaming de respuestas usando Server-Sent Events (SSE).

    El cliente recibe tokens del LLM en tiempo real, mejorando la experiencia
    de usuario al eliminar la espera por la respuesta completa.

    Formato de eventos SSE:
    - data: {"type": "token", "content": "palabra"}  → Token del LLM
    - data: {"type": "sources", "sources": [...]}     → Fuentes al final
    - data: {"type": "done", "tokens_used": 150}      → Señal de fin
    - data: {"type": "error", "content": "mensaje"}   → Error

    Uso desde JavaScript:
        const eventSource = new EventSource('/chat/stream', {method: 'POST', body: ...});
        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'token') appendToChat(data.content);
        };
    """
    start = time.time()

    async def event_generator():
        try:
            clean_query = extract_clean_query(request.message)
            detected_url = detect_url_in_query(clean_query)
            wants_search_flag = wants_web_search(clean_query)

            # Para scrape y web search, no hay streaming (son pre-procesados)
            if detected_url or wants_search_flag:
                yield f"data: {json.dumps({'type': 'info', 'content': 'Procesando...'})}\n\n"

                if detected_url:
                    content, title, error = await handle_scrape_mode(detected_url, clean_query)
                    if error:
                        yield f"data: {json.dumps({'type': 'error', 'content': error})}\n\n"
                        return

                    messages = [
                        {"role": "system", "content": "You are an expert web content analyst. Summarize the content."},
                        {"role": "user", "content": f"Request: {clean_query}\n\nContent: {content[:15000]}"},
                    ]
                    sources = [{"url": detected_url, "title": title, "type": "web_scrape"}]
                else:
                    formatted_results, sources_list, error = await handle_web_search_mode(clean_query)
                    if error:
                        yield f"data: {json.dumps({'type': 'error', 'content': error})}\n\n"
                        return

                    messages = [
                        {"role": "system", "content": "Answer based on search results. Cite with [1], [2]."},
                        {"role": "user", "content": f"Question: {clean_query}\n\nResults: {formatted_results}"},
                    ]
                    sources = [{"filename": s.get("title"), "url": s.get("url")} for s in sources_list]
            else:
                # RAG o Chat normal
                explicit_rag_request = wants_rag_search(clean_query)
                use_rag = explicit_rag_request
                sources = []

                tenant_collections = []
                if x_tenant_ids:
                    tenant_collections = [t.strip() for t in x_tenant_ids.split(",") if t.strip()]
                elif x_tenant_id:
                    tenant_collections = [x_tenant_id]
                if not tenant_collections:
                    tenant_collections = [os.getenv("QDRANT_COLLECTION", "documents")]
                if "webs" not in tenant_collections:
                    tenant_collections.append("webs")

                if use_rag:
                    results, sources, context_text = build_rag_context(clean_query, tenant_collections)
                    if not results:
                        yield f"data: {json.dumps({'type': 'token', 'content': 'No he encontrado contenido relevante en los documentos indexados.'})}\n\n"
                        yield f"data: {json.dumps({'type': 'done', 'tokens_used': 0})}\n\n"
                        return

                    messages = [
                        {"role": "system", "content": "Answer based on document context. Cite with [Document: name, Page: X]."},
                        {"role": "user", "content": f"Question: {clean_query}\n\nContext: {context_text}"},
                    ]
                else:
                    messages = [
                        {"role": "system", "content": "You are JARVIS, an intelligent RAG assistant. Respond naturally."},
                        {"role": "user", "content": request.message},
                    ]

            # Streaming del LLM
            stream = llm_client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=0.3,
                stream=True,
            )

            total_tokens = 0
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    total_tokens += 1
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            # Enviar fuentes al final
            if sources:
                yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'tokens_used': total_tokens, 'processing_time': time.time() - start})}\n\n"

        except Exception as e:
            logger.error(f"Error en chat stream: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

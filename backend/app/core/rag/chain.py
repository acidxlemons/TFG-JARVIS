# backend/app/core/rag/chain.py

"""

NO SE USA!!!!


RAG Chain (LCEL-like) para orquestar:
1) (opcional) Reescritura de consulta con historial
2) Recuperación de contexto (Qdrant)
3) Formateo de prompt con contexto y citas
4) Llamada al LLM (LiteLLM/OpenAI compatible)
5) Ensamblado de respuesta con metadatos y citas

Diseñado para usarse desde FastAPI o el agente.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any, Generator, Tuple
from dataclasses import dataclass
from datetime import datetime
import os
import logging

# LLM: cliente OpenAI-compatible (LiteLLM proxy u OpenAI directo)
from openai import OpenAI

# Local
from .retriever import RAGRetriever, RetrievalResult

logger = logging.getLogger(__name__)


# =========================
# Modelos de respuesta
# =========================

@dataclass
class Citation:
    source_id: str  # filename o ruta
    uri: Optional[str]  # si tienes URL pública o sharepoint link
    page: Optional[int]
    label: str       # "[filename p.X]"

@dataclass
class RAGAnswer:
    text: str
    citations: List[Citation]
    latency_ms: int
    sources_used: List[str]
    eval: Dict[str, Any]  # {"grounded": bool, "confidence": float}


# =========================
# Cadena principal de RAG
# =========================

DEFAULT_SYSTEM_PROMPT = """Eres un asistente empresarial preciso y conciso. 
Responde SOLO con información apoyada en el contexto proporcionado.
Cita SIEMPRE las fuentes usando el formato exacto entre corchetes, p. ej.: [contrato_2024.pdf p.3].
Si no hay información suficiente en el contexto, responde claramente que no se encontró evidencia.
No inventes. Sé específico y útil.
"""

USER_PROMPT_TEMPLATE = """Pregunta del usuario:
{question}

Contexto recuperado (fragmentos con citas):
{context}

Instrucciones de formato:
- Incluye las citas exactas en línea, justo tras cada afirmación clave (formato: [filename.ext p.N]).
- Si varias frases provienen del mismo fragmento, puedes reutilizar la misma cita.
- No incluyas información que no esté en el contexto.
"""


def _build_context_block(results: List[RetrievalResult]) -> str:
    """
    Genera el bloque de contexto para el prompt con el formato:
    [CITA] texto…
    """
    lines = []
    for r in results:
        # Cada chunk precedido de su cita para facilitar grounding del LLM
        lines.append(f"{r.citation} {r.text}".strip())
    return "\n\n".join(lines)


def _results_to_citations(results: List[RetrievalResult]) -> List[Citation]:
    out: List[Citation] = []
    for r in results:
        out.append(
            Citation(
                source_id=r.filename or r.source or "unknown",
                uri=None,  # si tienes un mapeo a URL externa, complétalo aquí
                page=r.page,
                label=r.citation,
            )
        )
    return out


class RAGChain:
    """
    Orquesta el flujo RAG. Se instancia con:
      - retriever: RAGRetriever
      - modelo LLM (vía cliente OpenAI Compatible)
    """

    def __init__(
        self,
        retriever: RAGRetriever,
        model: Optional[str] = None,
        openai_base_url: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ):
        self.retriever = retriever
        self.model = model or os.getenv("RAG_LLM_MODEL", "gpt-4o-mini")  # o el que tengas en LiteLLM
        base_url = openai_base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("LITELLM_BASE_URL")
        api_key = openai_api_key or os.getenv("OPENAI_API_KEY") or os.getenv("LITELLM_API_KEY")
        # El cliente OpenAI permite configurar un endpoint OpenAI-compatible (LiteLLM)
        self.client = OpenAI(base_url=base_url, api_key=api_key) if base_url else OpenAI(api_key=api_key)
        self.system_prompt = system_prompt

    # --------
    # Público
    # --------

    def invoke(
        self,
        question: str,
        *,
        top_k: int = 5,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        tenant_id: Optional[str] = None,
        filter_by_source: Optional[str] = None,
        filter_by_filenames: Optional[List[str]] = None,
        filter_date_range: Optional[Tuple[datetime, datetime]] = None,
        exclude_ocr: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 600,
        stream: bool = False,
    ) -> RAGAnswer | Generator[str, None, RAGAnswer]:
        """
        Ejecuta la cadena RAG completa.

        Si stream=True, devuelve un generador que emite texto incremental; al terminar,
        el generador retorna (StopIteration.value) un RAGAnswer completo.
        """
        # 1) Retrieve (con posible rewriting simple ya incluido en retriever.retrieve_with_context)
        results = self.retriever.retrieve_with_context(
            query=question,
            conversation_history=conversation_history,
            top_k=top_k,
            filter_by_source=filter_by_source,
            filter_by_filenames=filter_by_filenames,
            filter_date_range=filter_date_range,
            exclude_ocr=exclude_ocr,
            tenant_id=tenant_id,
        )

        # Guardrail: si no hay contexto suficiente, respuesta controlada
        if not results:
            text = (
                "No he encontrado información relevante en las fuentes indexadas para responder con garantías. "
                "Puedes intentar reformular la pregunta o aportar un documento relacionado."
            )
            return RAGAnswer(
                text=text,
                citations=[],
                latency_ms=0,
                sources_used=[],
                eval={"grounded": False, "confidence": 0.0},
            )

        # 2) Construir prompt con contexto y citas
        context_block = _build_context_block(results)
        user_prompt = USER_PROMPT_TEMPLATE.format(question=question, context=context_block)

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # 3) Llamada al LLM (con o sin streaming)
        if stream:
            return self._stream_completion(messages, results, temperature, max_tokens)
        else:
            return self._non_stream_completion(messages, results, temperature, max_tokens)

    # ----------------
    # Implementación
    # ----------------

    def _non_stream_completion(
        self,
        messages: List[Dict[str, str]],
        results: List[RetrievalResult],
        temperature: float,
        max_tokens: int,
    ) -> RAGAnswer:
        import time
        t0 = time.time()

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )

        latency_ms = int((time.time() - t0) * 1000)
        text = (resp.choices[0].message.content or "").strip()

        # Heurística de grounding: si no aparecen citas en el texto final, marcamos grounded=False
        grounded = any("[" in text and "]" in text for _ in [0]) and any(r.citation in text for r in results)
        confidence = 0.9 if grounded else 0.4

        return RAGAnswer(
            text=text,
            citations=_results_to_citations(results),
            latency_ms=latency_ms,
            sources_used=list({(r.source or r.filename) for r in results}),
            eval={"grounded": grounded, "confidence": confidence},
        )

    def _stream_completion(
        self,
        messages: List[Dict[str, str]],
        results: List[RetrievalResult],
        temperature: float,
        max_tokens: int,
    ) -> Generator[str, None, RAGAnswer]:
        """
        Generador que emite fragmentos de texto. Al finalizar, retorna el RAGAnswer completo.
        """
        import time
        t0 = time.time()

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        full_text_parts: List[str] = []
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                full_text_parts.append(delta)
                yield delta

        latency_ms = int((time.time() - t0) * 1000)
        final_text = "".join(full_text_parts).strip()

        grounded = any("[" in final_text and "]" in final_text for _ in [0]) and any(
            r.citation in final_text for r in results
        )
        confidence = 0.9 if grounded else 0.4

        answer = RAGAnswer(
            text=final_text,
            citations=_results_to_citations(results),
            latency_ms=latency_ms,
            sources_used=list({(r.source or r.filename) for r in results}),
            eval={"grounded": grounded, "confidence": confidence},
        )
        return answer

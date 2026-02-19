# backend/app/core/agent/base.py
"""
Agente RAG con LangChain
Sistema de citas obligatorio y memoria conversacional
"""

from __future__ import annotations

from typing import List, Dict, Optional, Any
from dataclasses import dataclass
import logging
import os
import re
import time

# LangChain (compatible con LiteLLM/OpenAI)
# Nota: en tu requirements usas langchain-openai==0.0.5
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import HumanMessage, AIMessage, SystemMessage
from langchain.tools import Tool

# Componentes locales
from ..rag.retriever import RAGRetriever, RetrievalResult
from ..memory.manager import MemoryManager, ConversationContext

logger = logging.getLogger(__name__)

# Acepta extensiones comunes en mayúsculas/minúsculas y permite espacios
CITATION_REGEX_VISIBLE = r'\[([^\]]+\.(?:pdf|docx|pptx|xlsx|txt|csv|jpg|jpeg|png))\s*(?:p\.(\d+))?\]'
TENANT_CLAIM = "tenant_id"


@dataclass
class AgentResponse:
    """Respuesta del agente con trazabilidad"""
    content: str
    sources: List[Dict]  # Documentos citados
    conversation_id: int
    tokens_used: int
    processing_time: float
    has_citations: bool


class RAGAgent:
    """
    Agente RAG Empresarial

    Características:
    1. RAG con búsqueda semántica en Qdrant
    2. Memoria conversacional por usuario (Postgres)
    3. Sistema de citas OBLIGATORIO
    4. Tools extensibles (web scraping, etc.)
    5. Resúmenes automáticos de conversaciones largas
    """

    # ==================== PROMPT SYSTEM ====================

    SYSTEM_PROMPT = """Eres un asistente de IA empresarial especializado en análisis de documentos.

REGLAS CRÍTICAS QUE DEBES SEGUIR SIEMPRE:

1. CITAS OBLIGATORIAS:
   - TODA información extraída de documentos DEBE incluir cita en formato: [nombre_archivo.ext p.X]
   - Ejemplo: "El contrato tiene duración de 12 meses [contrato_2024.pdf p.3]"
   - Si la información proviene de múltiples documentos, cita todos
   - NUNCA inventes citas ni nombres de archivos

2. TRANSPARENCIA:
   - Si no encuentras información en los documentos, dilo claramente
   - Indica cuando necesitas más contexto o documentos específicos
   - Si la confianza en la información es baja, menciónalo

3. CONTEXTO CONVERSACIONAL:
   - Ten en cuenta la conversación anterior del usuario
   - Si el usuario se refiere a “el otro contrato”, intenta identificarlo por el contexto previo

4. ESTRUCTURA DE RESPUESTAS:
   - Respuestas concisas pero completas
   - Usa viñetas para listas
   - Destaca información crítica
   - Sugiere próximos pasos cuando sea útil

5. DOCUMENTOS OCR:
   - Algunos documentos fueron procesados con OCR y pueden contener errores menores
   - Si algo parece extraño, adviértelo brevemente

IMPORTANTE:
- NO agregues información que no esté en el contexto recuperado.
- Si no hay evidencia suficiente, di “no encontrado en las fuentes”.
"""

    def __init__(
        self,
        retriever: RAGRetriever,
        memory_manager: MemoryManager,
        llm_base_url: Optional[str],
        llm_api_key: Optional[str],
        model_name: str = "llama3.1-8b",
        temperature: float = 0.1,
        max_context_docs: int = 5,
        default_tenant_id: Optional[str] = None,
    ):
        """
        Args:
            retriever: RAG retriever configurado
            memory_manager: Gestor de memoria conversacional
            llm_base_url: URL de LiteLLM/OpenAI-compatible
            llm_api_key: API key
            model_name: Nombre del modelo (en LiteLLM)
            temperature: Temperatura del modelo
            max_context_docs: Máximo de documentos en contexto
            default_tenant_id: tenant por defecto (si aplica multi-tenant)
        """
        self.retriever = retriever
        self.memory = memory_manager
        self.max_context_docs = max_context_docs
        self.default_tenant_id = default_tenant_id

        # Se usa en cada llamada a chat() para que las tools conozcan el tenant
        self._current_tenant: Optional[str] = default_tenant_id

        # Inicializar LLM
        logger.info(f"Inicializando LLM: {model_name} via {llm_base_url}")
        self.llm = ChatOpenAI(
            base_url=llm_base_url or os.getenv("LITELLM_URL") or os.getenv("OPENAI_BASE_URL"),
            api_key=llm_api_key or os.getenv("LITELLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
            model=model_name,
            temperature=temperature,
            streaming=False,  
        )

        # Crear agente con tools
        self.agent = self._create_agent()
        logger.info("RAG Agent inicializado")

    # =============== Creación del agente y tools ===============

    def _create_agent(self) -> AgentExecutor:
        """
        Configura el agente con una tool principal de búsqueda RAG.
        """

        search_tool = Tool(
            name="search_documents",
            description=(
                "Busca información en documentos de la empresa (RAG sobre Qdrant). "
                "Úsala cuando el usuario pregunte sobre contratos, políticas, informes, etc. "
                "Entrada: consulta en lenguaje natural. Salida: fragmentos relevantes con citas."
            ),
            func=self._search_documents_tool,
        )

        tools = [search_tool]

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        agent = create_openai_functions_agent(
            llm=self.llm,
            tools=tools,
            prompt=prompt,
        )

        return AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=False,
            max_iterations=3,
            handle_parsing_errors=True,
            return_intermediate_steps=False,
        )

    # =============== Tool: búsqueda en documentos ===============

    def _search_documents_tool(self, query: str) -> str:
        """
        Ejecuta el retriever y devuelve texto con fragmentos + citas.
        Respeta el tenant de la llamada actual (self._current_tenant).
        """
        try:
            # Determinar colección principal basada en tenant
            primary_collection = os.getenv("QDRANT_COLLECTION", "documents")
            tenant = self._current_tenant or self.default_tenant_id
            
            # Si el tenant implica una colección específica (multi-site sharepoint)
            if tenant and tenant.startswith("documents_"):
                primary_collection = tenant
            
            # Busqueda multi-colección: Principal + Webs
            # NOTA: 'webs' siempre se incluye para dar acceso a internet memory
            target_collections = [primary_collection]
            if "webs" not in target_collections:
                target_collections.append("webs")

            results = self.retriever.retrieve_multi_collection(
                query,
                collections=target_collections,
                top_k=self.max_context_docs,
                tenant_id=tenant, # Se pasa para filtrar dentro de la colección principal si aplica
            )
            
            if not results:
                return "No se encontraron documentos relevantes para esta consulta."

            return self._format_retrieval_snippets(results)

        except Exception as e:
            logger.error(f"Error en search_documents_tool: {e}")
            return f"Error buscando documentos: {str(e)}"

    @staticmethod
    def _format_retrieval_snippets(results: List[RetrievalResult]) -> str:
        parts = []
        for i, r in enumerate(results, 1):
            parts.append(
                f"{i}. {r.text}\n"
                f"   Fuente: {r.citation}\n"
                f"   Relevancia: {r.score:.2%}"
            )
        return "\n\n".join(parts)

    # ==================== MÉTODO PRINCIPAL ====================

    def chat(
        self,
        user_id: Optional[int],
        conversation_id: Optional[int],
        message: str,
        *,
        tenant_id: Optional[str] = None,
        azure_id: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None,
    ) -> AgentResponse:
        
    # Procesa el mensaje del usuario con memoria + agente RAG.
       
        start_time = time.time()
        logger.info(f"Procesando mensaje: '{(message or '')[:80]}'")

        # Asegurar usuario
        if azure_id:
            user_id = self.memory.get_or_create_user(azure_id, email, name)

        # Crear conversación si no existe
        if not conversation_id:
            if not user_id:
                raise ValueError("user_id es obligatorio si no se proporciona conversation_id")
            conversation_id = self.memory.create_conversation(user_id)

        # Guardar mensaje del usuario (sin métricas)
        self.memory.add_message(
            conversation_id=conversation_id,
            role="user",
            content=message,
        )

        # Historial
        context = self.memory.get_conversation_context(conversation_id)
        chat_history = self._format_chat_history(context)

        # Fijar tenant actual para tools
        self._current_tenant = tenant_id or self.default_tenant_id

        # Ejecutar agente
        try:
            agent_input = {"input": message, "chat_history": chat_history}
            result = self.agent.invoke(agent_input)

            response_text: str = (result.get("output") or "").strip()

            # Asegurar citas (guardrail): si faltan, añadimos sección de fuentes recuperadas
            sources = self._extract_citations(response_text)
            has_citations = len(sources) > 0

            if not has_citations:
                # Intento de grounding mínimo: recuperar y anexar fuentes
                retrieved = self.retriever.retrieve(
                    message,
                    top_k=min(self.max_context_docs, 3),
                    tenant_id=self._current_tenant or self.default_tenant_id,
                )
                if retrieved:
                    response_text = self._append_sources_section(response_text, retrieved)
                    sources = [
                        {
                            "filename": r.filename,
                            "page": r.page,
                            "citation": r.citation,
                            "score": r.score,
                        }
                        for r in retrieved
                    ]
                    has_citations = True
                else:
                    # Sin documentos → mensaje transparente
                    response_text = (
                        "No he encontrado evidencia en las fuentes disponibles para responder con garantías. "
                        "Si puedes indicar el documento o aportar más contexto, lo reviso al momento."
                    )

            # Métricas
            processing_time = time.time() - start_time
            tokens_used = self._estimate_tokens(message, response_text)
            processing_time_ms = int(processing_time * 1000)

            # Guardar respuesta del asistente con métricas
            self.memory.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=response_text,
                sources_used=sources,
                metadata={
                    "model": getattr(self.llm, "model", None) or getattr(self.llm, "model_name", None),
                    "temperature": getattr(self.llm, "temperature", None),
                    "tenant_id": self._current_tenant,
                },
                tokens_used=tokens_used,
                processing_time_ms=processing_time_ms,
            )

            return AgentResponse(
                content=response_text,
                sources=sources,
                conversation_id=conversation_id,
                tokens_used=tokens_used,
                processing_time=processing_time,
                has_citations=has_citations,
            )

        except Exception as e:
            logger.exception(f"Error en chat: {e}")
            error_msg = (
                "Disculpa, encontré un error procesando tu consulta. "
                "Por favor, intenta reformular tu pregunta o contacta al administrador."
            )

            # Guardamos el error como mensaje del asistente (sin métricas)
            self.memory.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=error_msg,
                metadata={"error": str(e), "tenant_id": self._current_tenant},
            )

            return AgentResponse(
                content=error_msg,
                sources=[],
                conversation_id=conversation_id,
                tokens_used=0,
                processing_time=time.time() - start_time,
                has_citations=False,
            )


    # ==================== MÉTODOS AUXILIARES ====================

    def _format_chat_history(self, context: ConversationContext) -> List:
        """
        Formatea historial de conversación para LangChain (incluye resumen si existe).
        """
        history: List = []
        if getattr(context, "summary", None):
            history.append(SystemMessage(content=f"Resumen de conversación previa:\n{context.summary}"))

        for msg in context.messages:
            role = msg.get("role")
            if role == "user":
                history.append(HumanMessage(content=msg.get("content", "")))
            elif role == "assistant":
                history.append(AIMessage(content=msg.get("content", "")))
        return history

    def _extract_citations(self, text: str) -> List[Dict]:
        """
        Extrae citas del texto de respuesta. Formato esperado: [archivo.ext p.N]
        """
        matches = re.findall(CITATION_REGEX_VISIBLE, text, re.IGNORECASE)
        sources: List[Dict] = []
        seen: set[str] = set()

        for filename, page in matches:
            key = f"{filename}_{page or ''}"
            if key in seen:
                continue
            sources.append(
                {
                    "filename": filename,
                    "page": int(page) if page else None,
                    "citation": f"[{filename}{' p.' + page if page else ''}]",
                }
            )
            seen.add(key)
        return sources

    @staticmethod
    def _append_sources_section(text: str, retrieval_results: List[RetrievalResult]) -> str:
        lines = ["\n\n---", "Fuentes consultadas:"]
        for r in retrieval_results:
            lines.append(f"- {r.citation}")
        return (text + ("\n" if text else "") + "\n".join(lines)).strip()

    @staticmethod
    def _estimate_tokens(input_text: str, output_text: str) -> int:
        """
        Estimación simple de tokens (≈ 4 chars/token).
        """
        total_chars = len(input_text or "") + len(output_text or "")
        return max(1, total_chars // 4)


# ============================================
# Validador ligero de citas (opcional)
# ============================================

class CitationValidator:
    """
    Valida que la respuesta incluya citas y que el formato sea correcto.
    """

    @staticmethod
    def validate_response(response: str, sources: List[Dict]) -> Dict[str, Any]:
        citations_in_text = re.findall(r'\[([^\]]+)\]', response or "")
        sources_cited = set()
        for cit in citations_in_text:
            for s in sources:
                if s.get("filename") and s["filename"] in cit:
                    sources_cited.add(s["filename"])

        missing = sorted(set(s["filename"] for s in sources if s.get("filename")) - sources_cited)
        invalid = []
        valid_pattern = re.compile(
            r'\[.+\.(?:pdf|docx|pptx|xlsx|txt|csv|jpg|jpeg|png)(?:\s+p\.\d+)?\]',
            re.IGNORECASE
        )
        for raw in citations_in_text:
            full = f"[{raw}]"
            if not valid_pattern.match(full):
                invalid.append(full)

        return {
            "has_citations": len(citations_in_text) > 0,
            "total_citations": len(citations_in_text),
            "sources_used": len(sources),
            "sources_cited": len(sources_cited),
            "missing_citations": missing,
            "invalid_format": invalid,
            "is_valid": len(missing) == 0 and len(invalid) == 0,
        }

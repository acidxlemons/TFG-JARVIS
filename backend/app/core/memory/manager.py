# backend/app/core/memory/manager.py
"""
Sistema de Memoria Conversacional por Usuario
Almacena historial en Postgres y genera resúmenes automáticos
"""

from __future__ import annotations

from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging
import os

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
try:
    # Postgres recomendado
    from sqlalchemy.dialects.postgresql import JSONB as JSONType
except Exception:  # pragma: no cover
    # Fallback si no es Postgres
    from sqlalchemy import JSON as JSONType  # type: ignore

logger = logging.getLogger(__name__)

Base = declarative_base()


# ============================================
# MODELOS DE BASE DE DATOS
# ============================================

class User(Base):
    """Tabla de usuarios (desde Azure SSO)"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    azure_id = Column(String(255), unique=True, nullable=False, index=True)
    # Mantengo NOT NULL pero meto fallback al crear si Azure no trae email
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    conversations = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_users_azure_id", "azure_id"),
        Index("ix_users_email", "email"),
    )


class Conversation(Base):
    """Conversación (sesión de chat)"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(500))  # Auto-generado del primer mensaje
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_archived = Column(Boolean, default=False)

    # Resumen de la conversación (generado periódicamente)
    summary = Column(Text, nullable=True)
    summary_generated_at = Column(DateTime, nullable=True)

    # Metadata adicional  ⬅️  ATRIBUTO PYTHON 'meta', COLUMNA SQL 'metadata'
    meta = Column('metadata', JSONType, default=dict)

    # Relaciones
    user = relationship("User", back_populates="conversations")
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at.asc()",
    )

    __table_args__ = (
        Index("ix_conversations_user_id", "user_id"),
        Index("ix_conversations_updated_at", "updated_at"),
        Index("ix_conversations_is_archived", "is_archived"),
    )


class Message(Base):
    """Mensaje individual en una conversación"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)

    role = Column(String(50), nullable=False)  # 'user', 'assistant', 'system'
    content = Column(Text, nullable=False)

    # Metadata de RAG
    sources_used = Column(JSONType, nullable=True)  # Lista de documentos citados
    retrieval_count = Column(Integer, default=0)  # Cuántos docs se recuperaron

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Métricas de ejecución (alineado con init.sql)
    tokens_used = Column(Integer, default=0)
    processing_time_ms = Column(Integer, nullable=True)

    # Metadata adicional (tokens, latencia, modelo, tenant, errores, etc.)
    # ⬅️  ATRIBUTO PYTHON 'meta', COLUMNA SQL 'metadata'
    meta = Column('metadata', JSONType, default=dict)

    # Relaciones
    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )


class IngestionStatus(Base):
    """Estado de ingestión de documentos"""
    __tablename__ = "ingestion_status"

    filename = Column(String(255), primary_key=True)
    status = Column(String(50), nullable=False)  # pending, processing, completed, failed
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_ingestion_status_updated_at", "updated_at"),
    )



# ============================================
# GESTOR DE MEMORIA
# ============================================

@dataclass
class ConversationContext:
    """Contexto de conversación para el LLM"""
    conversation_id: int
    user_id: int
    messages: List[Dict]  # [{"role": "user", "content": "..."}]
    summary: Optional[str]  # Resumen de mensajes antiguos
    total_messages: int


class MemoryManager:
    """
    Gestor de Memoria Conversacional

    Funciones:
    1. Almacenar mensajes de usuarios
    2. Recuperar historial por conversación
    3. Generar resúmenes automáticos
    4. Limpiar conversaciones antiguas
    """

    def __init__(
        self,
        database_url: str,
        summarizer_llm=None,  # LLM para generar resúmenes (opcional)
        max_messages_before_summary: int = 10,
        context_window_size: int = 5,  # Últimos N mensajes siempre incluidos
    ):
        # Conexión a Postgres
        self.engine = create_engine(database_url, pool_pre_ping=True, future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, expire_on_commit=False)

        self.summarizer_llm = summarizer_llm
        self.max_messages_before_summary = max(1, int(max_messages_before_summary))
        self.context_window_size = max(1, int(context_window_size))

        # Permite ajustar cada cuánto se regenera el resumen vía env
        self.summary_ttl_seconds = int(os.getenv("SUMMARY_TTL_SECONDS", str(3600)))

        logger.info("MemoryManager inicializado")

    # ==================== GESTIÓN DE USUARIOS ====================

    def get_or_create_user(self, azure_id: str, email: Optional[str], name: Optional[str]) -> int:
        """
        Obtiene o crea usuario desde Azure SSO
        Returns: user_id
        """
        session = self.Session()
        try:
            user = session.query(User).filter(User.azure_id == azure_id).one_or_none()
            if user:
                user.last_active = datetime.utcnow()
                if email and user.email != email:
                    user.email = email  # resync si cambia en el IdP
                if name and user.name != name:
                    user.name = name
                session.commit()
                return user.id

            # Fallback de email si Azure no lo trae (evita violar NOT NULL/UNIQUE)
            safe_email = email or f"{azure_id}@unknown.local"

            user = User(azure_id=azure_id, email=safe_email, name=name or "")
            session.add(user)
            session.commit()
            logger.info(f"Usuario creado: {safe_email} (ID: {user.id})")
            return user.id
        except Exception as e:
            session.rollback()
            logger.error(f"Error get_or_create_user: {e}")
            raise
        finally:
            session.close()

    # ==================== GESTIÓN DE CONVERSACIONES ====================

    def create_conversation(self, user_id: int, title: Optional[str] = None) -> int:
        """Crea nueva conversación y devuelve su ID"""
        session = self.Session()
        try:
            conversation = Conversation(user_id=user_id, title=title or "Nueva conversación")
            session.add(conversation)
            session.commit()
            logger.info(f"Conversación creada: {conversation.id} para user {user_id}")
            return conversation.id
        except Exception as e:
            session.rollback()
            logger.error(f"Error create_conversation: {e}")
            raise
        finally:
            session.close()

    def get_user_conversations(
        self,
        user_id: int,
        include_archived: bool = False,
        limit: int = 20,
    ) -> List[Dict]:
        """Lista conversaciones de un usuario"""
        session = self.Session()
        try:
            q = session.query(Conversation).filter(Conversation.user_id == user_id)
            if not include_archived:
                q = q.filter(Conversation.is_archived.is_(False))
            conversations = (
                q.order_by(Conversation.updated_at.desc())
                .limit(max(1, int(limit)))
                .all()
            )
            # Nota: len(c.messages) potencialmente hace N+1; aceptable a estos tamaños
            return [
                {
                    "id": c.id,
                    "title": c.title,
                    "created_at": c.created_at.isoformat(),
                    "updated_at": c.updated_at.isoformat(),
                    "message_count": len(c.messages),
                    "has_summary": c.summary is not None,
                }
                for c in conversations
            ]
        finally:
            session.close()

    # ==================== GESTIÓN DE MENSAJES ====================

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        sources_used: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
        tokens_used: Optional[int] = None,
        processing_time_ms: Optional[int] = None,
    ) -> int:
        """
        Añade mensaje a una conversación y actualiza metadatos básicos.
        Returns: message_id
        """
        session = self.Session()
        try:
            if role not in {"user", "assistant", "system"}:
                raise ValueError(f"role inválido: {role}")

            convo = session.get(Conversation, conversation_id)
            if not convo:
                raise ValueError(f"Conversación {conversation_id} no encontrada")

            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content or "",
                sources_used=sources_used or [],
                retrieval_count=len(sources_used) if sources_used else 0,
                tokens_used=int(tokens_used or 0),
                processing_time_ms=int(processing_time_ms) if processing_time_ms is not None else None,
                meta=metadata or {},
            )
            session.add(message)

            # Actualizar timestamp de conversación
            convo.updated_at = datetime.utcnow()

            # Auto-generar título si es el primer mensaje del usuario
            if role == "user" and (not convo.title or convo.title == "Nueva conversación"):
                convo.title = self._generate_title(content)

            session.commit()
            logger.debug(f"Mensaje añadido a conversación {conversation_id}")
            return message.id
        except Exception as e:
            session.rollback()
            logger.error(f"Error add_message: {e}")
            raise
        finally:
            session.close()

    def get_conversation_context(self, conversation_id: int, max_tokens: Optional[int] = None) -> ConversationContext:
        """
        Obtiene contexto de conversación para el LLM.

        Lógica:
        - Si hay <= max_messages_before_summary: devuelve todos.
        - Si hay >, genera (o reutiliza) resumen para los antiguos y devuelve resumen + últimos N.
        """
        session = self.Session()
        try:
            convo = session.get(Conversation, conversation_id)
            if not convo:
                raise ValueError(f"Conversación {conversation_id} no encontrada")

            messages: List[Message] = (
                session.query(Message)
                .filter(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
                .all()
            )
            total = len(messages)

            # Caso simple: pocos mensajes
            if total <= self.max_messages_before_summary:
                context_messages = [
                    {"role": m.role, "content": m.content, "sources": m.sources_used} for m in messages
                ]
                return ConversationContext(
                    conversation_id=conversation_id,
                    user_id=convo.user_id,
                    messages=context_messages,
                    summary=None,
                    total_messages=total,
                )

            # Caso con resumen
            should_regenerate = (
                convo.summary is None
                or (
                    convo.summary_generated_at
                    and (datetime.utcnow() - convo.summary_generated_at) > timedelta(seconds=self.summary_ttl_seconds)
                )
            )

            if should_regenerate:
                # Resumimos todos salvo la ventana más reciente
                to_summarize = messages[:-self.context_window_size] if self.context_window_size < total else messages
                summary = self._generate_summary(to_summarize)
                convo.summary = summary
                convo.summary_generated_at = datetime.utcnow()
                session.commit()
                logger.info(f"Resumen generado para conversación {conversation_id}")

            recent_msgs = messages[-self.context_window_size:] if self.context_window_size < total else messages
            context_messages = [
                {"role": m.role, "content": m.content, "sources": m.sources_used} for m in recent_msgs
            ]

            # Truncado blando por tokens si se pide
            if max_tokens:
                context_messages = self._truncate_by_tokens(context_messages, max_tokens)

            return ConversationContext(
                conversation_id=conversation_id,
                user_id=convo.user_id,
                messages=context_messages,
                summary=convo.summary,
                total_messages=total,
            )
        except Exception as e:
            logger.error(f"Error get_conversation_context: {e}")
            raise
        finally:
            session.close()

    # ==================== RESÚMENES AUTOMÁTICOS ====================

    def _generate_summary(self, messages: List[Message]) -> str:
        """
        Genera resumen de mensajes antiguos usando LLM (si está configurado).
        """
        if not messages:
            return "Sin mensajes previos."
        if not self.summarizer_llm:
            return f"Conversación con {len(messages)} mensajes previos."

        try:
            # Construir texto de la conversación (truncado por seguridad)
            joined = "\n\n".join(
                f"{m.role.upper()}: {m.content[:1000]}"  # limitar cada mensaje
                for m in messages
            )
            prompt = (
                "Resume la siguiente conversación en 2-3 párrafos concisos. "
                "Destaca: temas principales, preguntas clave del usuario, documentos citados y conclusiones o tareas.\n\n"
                f"Conversación:\n{joined}\n\nResumen:"
            )
            raw = self.summarizer_llm.invoke(prompt)
            summary = self._llm_text(raw)
            return summary.strip() if summary else f"Conversación con {len(messages)} mensajes previos."
        except Exception as e:
            logger.error(f"Error generando resumen: {e}")
            return f"Conversación con {len(messages)} mensajes previos (resumen no disponible)."

    # ==================== UTILIDADES ====================

    def _generate_title(self, first_message: str) -> str:
        """Genera título simple desde el primer mensaje del usuario."""
        s = (first_message or "").strip()
        if len(s) <= 50:
            return s if s else "Nueva conversación"
        return s[:50].rstrip() + "…"

    def _truncate_by_tokens(self, messages: List[Dict], max_tokens: int) -> List[Dict]:
        """
        Truncado muy aproximado (1 token ≈ 4 chars) desde el principio,
        conservando los últimos mensajes.
        """
        if max_tokens <= 0 or not messages:
            return messages
        budget_chars = max_tokens * 4
        # contamos de atrás adelante para preservar los más recientes
        out: List[Dict] = []
        used = 0
        for msg in reversed(messages):
            chunk = msg.get("content", "") or ""
            size = len(chunk)
            if used + size <= budget_chars:
                out.append(msg)
                used += size
            else:
                # incluir parte final si queda presupuesto
                remaining = budget_chars - used
                if remaining > 0:
                    clipped = {**msg, "content": chunk[-remaining:]}
                    out.append(clipped)
                break
        return list(reversed(out))

    @staticmethod
    def _llm_text(raw) -> str:
        """Normaliza respuesta del LLM a string."""
        # Compat con LangChain ChatOpenAI, llamadores directos, etc.
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        # LangChain LLMResult-like
        try:
            content = getattr(raw, "content", None)
            if isinstance(content, str):
                return content
        except Exception:
            pass
        # OpenAI-style dicts
        if isinstance(raw, dict):
            # e.g., {"choices":[{"message":{"content":"..."}}]}
            try:
                return (
                    raw.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
            except Exception:
                return str(raw)
        return str(raw)

    # ==================== LIMPIEZA Y MANTENIMIENTO ====================

    def archive_conversation(self, conversation_id: int) -> None:
        """Archiva conversación (no la elimina)"""
        session = self.Session()
        try:
            convo = session.get(Conversation, conversation_id)
            if convo and not convo.is_archived:
                convo.is_archived = True
                session.commit()
                logger.info(f"Conversación {conversation_id} archivada")
        finally:
            session.close()

    def delete_old_conversations(self, days: int = 90) -> int:
        """
        Elimina conversaciones antiguas archivadas.
        Returns: número de conversaciones eliminadas
        """
        session = self.Session()
        try:
            cutoff = datetime.utcnow() - timedelta(days=int(days))
            deleted = (
                session.query(Conversation)
                .filter(Conversation.is_archived.is_(True))
                .filter(Conversation.updated_at < cutoff)
                .delete(synchronize_session=False)
            )
            session.commit()
            logger.info(f"Eliminadas {deleted} conversaciones antiguas")
            return int(deleted or 0)
        finally:
            session.close()

    # ==================== ESTADÍSTICAS ====================

    def get_user_stats(self, user_id: int) -> Dict:
        """Estadísticas del usuario"""
        session = self.Session()
        try:
            user = session.get(User, user_id)
            if not user:
                return {}
            total_conversations = session.query(Conversation).filter(Conversation.user_id == user_id).count()
            total_messages = (
                session.query(Message)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .filter(Conversation.user_id == user_id)
                .count()
            )
            return {
                "user_id": user_id,
                "email": user.email,
                "name": user.name,
                "total_conversations": total_conversations,
                "total_messages": total_messages,
                "member_since": user.created_at.isoformat(),
                "last_active": user.last_active.isoformat(),
            }
        finally:
            session.close()

    # ==================== GESTIÓN DE ESTADO DE INGESTIÓN ====================

    def update_ingestion_status(self, filename: str, status: str, message: Optional[str] = None) -> None:
        """Actualiza el estado de ingestión de un archivo"""
        session = self.Session()
        try:
            # Upsert
            obj = session.get(IngestionStatus, filename)
            if not obj:
                obj = IngestionStatus(filename=filename, status=status, message=message)
                session.add(obj)
            else:
                obj.status = status
                if message is not None:
                    obj.message = message
                # updated_at se actualiza solo
            
            session.commit()
            logger.info(f"Estado actualizado para {filename}: {status}")
        except Exception as e:
            session.rollback()
            logger.error(f"Error update_ingestion_status: {e}")
        finally:
            session.close()

    def get_ingestion_status(self, limit: int = 20) -> List[Dict]:
        """Obtiene los estados más recientes"""
        session = self.Session()
        try:
            items = (
                session.query(IngestionStatus)
                .order_by(IngestionStatus.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "filename": i.filename,
                    "status": i.status,
                    "message": i.message,
                    "updated_at": i.updated_at.isoformat(),
                }
                for i in items
            ]
        finally:
            session.close()

    def delete_ingestion_status(self, filename: str) -> None:
        """Elimina el estado de un archivo (ej. cuando se borra)"""
        session = self.Session()
        try:
            obj = session.get(IngestionStatus, filename)
            if obj:
                session.delete(obj)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Error delete_ingestion_status: {e}")
        finally:
            session.close()

    def cleanup_old_statuses(self, days: int = 30) -> int:
        """Elimina estados de ingestión antiguos (mantenimiento)"""
        session = self.Session()
        try:
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            deleted = (
                session.query(IngestionStatus)
                .filter(IngestionStatus.updated_at < cutoff)
                .filter(IngestionStatus.status.in_(["completed", "deleted", "failed"]))
                .delete(synchronize_session=False)
            )
            session.commit()
            logger.info(f"Limpiados {deleted} estados de ingestión antiguos")
            return int(deleted or 0)
        except Exception as e:
            session.rollback()
            logger.error(f"Error cleanup_old_statuses: {e}")
            return 0
        finally:
            session.close()


# ============================================
# EJEMPLO DE USO
# ============================================

if __name__ == "__main__":
    # Cambia la URL a tu entorno local si quieres probar rápidamente
    memory = MemoryManager(
        database_url="postgresql://rag_user:changeme@localhost:5432/rag_system",
        max_messages_before_summary=10,
        context_window_size=5,
    )

    # Crear usuario (desde Azure SSO)
    user_id = memory.get_or_create_user(
        azure_id="azure-user-123",
        email=None,  # demo: sin email → fallback seguro
        name="Juan Pérez",
    )

    # Crear conversación
    conv_id = memory.create_conversation(user_id, title="Consulta sobre contratos")

    # Añadir mensajes
    memory.add_message(conv_id, role="user", content="¿Cuál es el plazo del contrato X?")
    memory.add_message(
        conv_id,
        role="assistant",
        content="El contrato tiene un plazo de 12 meses según la cláusula 5. [contrato_X.pdf p.3]",
        sources_used=[{"filename": "contrato_X.pdf", "page": 3, "citation": "[contrato_X.pdf p.3]"}],
    )

    # Obtener contexto para el LLM
    context = memory.get_conversation_context(conv_id)
    print(f"Conversación {context.conversation_id} (mensajes totales: {context.total_messages})")
    if context.summary:
        print(f"Resumen: {context.summary[:120]}…")
    print("Mensajes recientes:")
    for msg in context.messages:
        print(f"- {msg['role']}: {msg['content'][:100]}…")

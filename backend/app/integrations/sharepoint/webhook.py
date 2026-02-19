# backend/app/integrations/sharepoint/webhook.py
"""
Webhook handler para notificaciones de Microsoft Graph / SharePoint.

- Valida el validationtoken (handshake inicial de Graph).
- Verifica clientState (anti-spoofing).
- Encola el procesamiento del recurso cambiado vía BackgroundTasks.
- Pensado para montarse como APIRouter y usarse desde FastAPI.

Uso:
    from .webhook import build_router

    router = build_router(
        expected_client_state=os.getenv("WEBHOOK_SECRET", "changeme"),
        on_change=mi_callback  # async def on_change(resource: str, change_type: str) -> None
    )
    app.include_router(router, prefix="/webhooks", tags=["Webhooks"])
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

logger = logging.getLogger(__name__)

# Firma del callback que procesará el cambio
OnChangeFn = Callable[[str, str], None] | Callable[[str, str], "awaitable"]


def build_router(
    *,
    expected_client_state: str,
    on_change: OnChangeFn,
    path: str = "/sharepoint",
) -> APIRouter:
    """
    Construye un APIRouter para el webhook de SharePoint.

    Args:
        expected_client_state: secreto a comparar con notification.clientState
        on_change: callback que procesará (resource, changeType)
        path: subruta del router (default: /sharepoint)

    Returns:
        APIRouter listo para incluir en FastAPI.
    """
    router = APIRouter()

    @router.get(path)
    async def validation(validationtoken: Optional[str] = None):
        """
        Graph hace una llamada GET con ?validationtoken=... para validar el endpoint.
        Debemos devolver ese token sin más.
        """
        if validationtoken:
            logger.info("Validando webhook de SharePoint (GET handshake)")
            # FastAPI devuelve JSON por defecto; Graph acepta 200 con body=token en texto.
            # Devolvemos dict por compatibilidad con tu main.py actual.
            return {"validationResponse": validationtoken}
        # Si alguien entra sin token, 400.
        raise HTTPException(status_code=400, detail="Missing validationtoken")

    @router.post(path)
    async def notify(
        request: Request,
        background_tasks: BackgroundTasks,
        validationtoken: Optional[str] = Header(None, alias="validationtoken"),
    ):
        """
        Notificaciones de cambios (POST con cuerpo JSON):
        {
          "value": [
            {
              "subscriptionId": "...",
              "clientState": "...",
              "resource": "/sites/{siteId}/drive/items/{itemId}",
              "changeType": "updated",
              ...
            }
          ]
        }
        """
        # Si Graph decide enviar otra validación vía POST con header validationtoken:
        if validationtoken:
            logger.info("Validación (POST) de SharePoint con validationtoken")
            return {"validationResponse": validationtoken}

        try:
            body = await request.json()
            events = body.get("value", [])
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        if not events:
            raise HTTPException(status_code=400, detail="Empty change notification")

        accepted = 0
        for ev in events:
            client_state = ev.get("clientState")
            resource = ev.get("resource")
            change_type = ev.get("changeType", "updated")

            if client_state != expected_client_state:
                logger.warning("Webhook rechazado por clientState inválido")
                continue

            if not resource:
                logger.warning("Evento sin 'resource' recibido, ignorando")
                continue

            # Encolar el procesamiento real
            background_tasks.add_task(_run_on_change, on_change, resource, change_type)
            accepted += 1

        if accepted == 0:
            raise HTTPException(status_code=403, detail="No valid events")

        return {"status": "accepted", "processed": accepted}

    return router


async def _run_on_change(on_change: OnChangeFn, resource: str, change_type: str):
    """Wrapper que soporta callbacks sync o async."""
    try:
        ret = on_change(resource, change_type)
        if hasattr(ret, "__await__"):
            await ret  # si es async
    except Exception as e:
        logger.error(f"Error procesando cambio SharePoint: {e}")

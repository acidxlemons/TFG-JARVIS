# backend/app/api/webhooks.py
"""
Router de Webhooks — Integración con SharePoint

Endpoint para recibir notificaciones de cambios en SharePoint.
Microsoft envía webhooks cuando se crean, modifican o eliminan documentos
en las bibliotecas de SharePoint configuradas.

Flujo de webhook:
1. Registro: Se registra el webhook con Microsoft (externo al sistema).
2. Validación: SharePoint envía GET con ?validationtoken=xxx → respondemos con el token.
3. Notificaciones: SharePoint envía POST con cambios → procesamos en background.
"""

import os
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Query

from app.schemas.webhooks import SharePointWebhookPayload
from app.state import app_state

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhooks/sharepoint", tags=["Webhooks"])
async def sharepoint_webhook(
    payload: SharePointWebhookPayload,
    background_tasks: BackgroundTasks,
    validation_token: Optional[str] = Query(None, alias="validationtoken"),
):
    """
    Endpoint para webhooks de SharePoint.

    Microsoft envía:
    1. Validación inicial (con validationtoken en query)
    2. Notificaciones de cambios (payload.value[])
    """
    # Paso 1: Validación inicial
    if validation_token:
        logger.info("Validando webhook de SharePoint...")
        return {"validationResponse": validation_token}

    # Paso 2: Procesar notificaciones
    for notification in payload.value:
        logger.info(f"Notificación de SharePoint: {notification.changeType} en {notification.resource}")

        # Validar clientState
        expected_state = os.getenv("WEBHOOK_SECRET", "changeme")
        if notification.clientState != expected_state:
            logger.warning("clientState inválido en notificación de SharePoint")
            continue

        background_tasks.add_task(
            process_sharepoint_change,
            resource=notification.resource,
            change_type=notification.changeType,
        )

    return {"status": "accepted"}


async def process_sharepoint_change(resource: str, change_type: str):
    """
    Procesa un cambio de SharePoint (placeholder).

    En una implementación completa:
    1. Descargar el archivo nuevo/modificado del recurso.
    2. Llamar a process_document() para re-indexar.
    3. Si es un borrado, eliminar chunks de Qdrant.
    """
    logger.info(f"Procesando cambio de SharePoint: {change_type} - {resource}")
    pass

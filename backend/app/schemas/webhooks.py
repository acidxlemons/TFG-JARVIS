# backend/app/schemas/webhooks.py
"""
Esquemas Pydantic para webhooks de SharePoint.

Microsoft SharePoint envía notificaciones de cambios a este sistema cuando
se crean, modifican o eliminan documentos en las bibliotecas configuradas.

Flujo de webhooks:
1. Al registrar el webhook, SharePoint envía una validación (GET con validationtoken).
2. Cuando un documento cambia, SharePoint envía un POST con una lista de notificaciones.
3. Cada notificación contiene el recurso modificado y el tipo de cambio.
"""

from typing import List
from pydantic import BaseModel


class SharePointNotificationItem(BaseModel):
    """
    Elemento individual de notificación de SharePoint.

    Campos:
    - subscriptionId: ID de la suscripción al webhook.
    - clientState: Token de verificación (debe coincidir con WEBHOOK_SECRET).
    - resource: Ruta del recurso modificado en SharePoint.
    - changeType: Tipo de cambio: "created", "updated", "deleted".
    """
    subscriptionId: str
    clientState: str
    resource: str
    changeType: str


class SharePointWebhookPayload(BaseModel):
    """
    Payload estándar de webhook de SharePoint.

    Microsoft envía un array de notificaciones en el campo "value".
    Pueden llegar múltiples cambios en un solo POST.
    """
    value: List[SharePointNotificationItem]

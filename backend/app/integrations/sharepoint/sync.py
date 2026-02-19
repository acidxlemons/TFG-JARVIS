# backend/app/integrations/sharepoint/sync.py
"""
Servicio de sincronización SharePoint → pipeline de indexación.

- Orquestra el flujo: detectar cambios (delta), descargar, procesar e indexar.
- No acopla al stack (OCR/Chunker/Qdrant); inyecta un `processor` callback.
- Incluye métodos para full_sync (seed inicial) y delta_sync (operación continua).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .client import SharePointClient, SharePointSynchronizer

logger = logging.getLogger(__name__)

# Firma del procesador externo:
#   async def processor(local_path: str, filename: str, metadata: Dict) -> None
# o bien sync:
#   def processor(local_path: str, filename: str, metadata: Dict) -> None
ProcessorFn = Callable[[str, str, Dict], None] | Callable[[str, str, Dict], "awaitable"]


@dataclass
class SyncConfig:
    local_dir: str = "./data/sharepoint"
    delta_token_file: str = "./sharepoint_delta.txt"
    include_metadata: Optional[Dict] = None  # metadata extra a adjuntar (tenant, ruta, etiquetas…)


class SharePointSyncService:
    """
    Fachada de alto nivel para sincronizar y mandar a indexar.
    """

    def __init__(self, client: SharePointClient, processor: ProcessorFn, config: Optional[SyncConfig] = None):
        self.client = client
        self.processor = processor
        self.config = config or SyncConfig()
        self.sync = SharePointSynchronizer(
            client=self.client,
            local_dir=self.config.local_dir,
            delta_token_file=self.config.delta_token_file,
        )

    async def full_sync(self) -> List[Dict]:
        """
        Descarga todos los archivos de la carpeta base y los procesa.
        """
        logger.info("Full sync SharePoint iniciado…")
        downloaded = self.sync.full_sync()
        await self._process_batch(downloaded)
        logger.info("Full sync SharePoint finalizado")
        return downloaded

    async def delta_sync(self) -> List[Dict]:
        """
        Sincronización incremental: procesa solo nuevos/modificados.
        """
        logger.info("Delta sync SharePoint iniciado…")
        changed = self.sync.sync()
        await self._process_batch(changed)
        logger.info("Delta sync SharePoint finalizado")
        return changed

    async def handle_change_notification(self, resource: str, change_type: str):
        """
        Callback para el webhook: con el resource del evento hacemos un delta refresh.
        Graph a veces manda múltiples eventos; la estrategia simple es ejecutar delta_sync.
        """
        logger.info(f"Webhook recibido: {change_type} → {resource}")
        await self.delta_sync()

    async def _process_batch(self, items: List[Dict]):
        """
        Llama al processor por cada archivo descargado.
        """
        for it in items:
            try:
                local_path = it["local_path"]
                filename = Path(local_path).name
                meta = {
                    "sharepoint_file_id": it.get("file_id"),
                    "sharepoint_modified_at": it.get("modified_at"),
                    "source": "sharepoint",
                }
                if self.config.include_metadata:
                    meta.update(self.config.include_metadata)

                res = self.processor(local_path, filename, meta)
                if hasattr(res, "__await__"):
                    await res  # soporta processor async
            except Exception as e:
                logger.error(f"Error procesando {it.get('name')}: {e}")

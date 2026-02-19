# services/indexer/app/multi_site_sync.py
"""
Multi-Site SharePoint Synchronizer

Gestiona la sincronización de múltiples sitios SharePoint simultáneamente.
Cada sitio se sincroniza a una colección Qdrant separada (multi-tenant).
"""

from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from app.integrations.sharepoint.client import SharePointClient, SharePointSynchronizer

logger = logging.getLogger(__name__)


@dataclass
class SiteConfig:
    """Configuración de un sitio SharePoint"""
    name: str
    site_id: str
    folder_path: str
    collection_name: str
    enabled: bool = True
    description: str = ""
    drive_id: Optional[str] = None


@dataclass
class SyncResult:
    """Resultado de sincronización de un archivo"""
    site_name: str
    collection_name: str
    file_id: str
    file_name: str
    local_path: str
    modified_at: Optional[str] = None
    deleted: bool = False
    error: Optional[str] = None


class MultiSiteSynchronizer:
    """
    Gestiona sincronización de múltiples sitios SharePoint.
    
    Características:
    - Carga configuración desde JSON
    - Crea un SharePointSynchronizer por cada sitio
    - Sincroniza todos los sitios en paralelo o secuencial
    - Cada sitio → tenant_id diferente → colección Qdrant separada
    """
    
    def __init__(
        self,
        config_path: str,
        base_watch_folder: str,
        azure_tenant_id: str,
        azure_client_id: str,
        azure_client_secret: str,
    ):
        self.config_path = Path(config_path)
        self.base_watch_folder = Path(base_watch_folder)
        self.azure_tenant_id = azure_tenant_id
        self.azure_client_id = azure_client_id
        self.azure_client_secret = azure_client_secret
        
        self.config: Dict[str, Any] = {}
        self.sites: List[SiteConfig] = []
        self.synchronizers: Dict[str, Dict] = {}
        
        self._load_config()
        self._init_synchronizers()
    
    def _load_config(self) -> None:
        """Carga configuración desde archivo JSON"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        
        # Parsear sitios
        for site_data in self.config.get("sites", []):
            # Saltar sitios con site_id pendiente
            site_id = site_data.get("site_id", "")
            if site_id.startswith("PENDING_"):
                logger.warning(f"Sitio '{site_data.get('name')}' tiene site_id pendiente, saltando...")
                continue
            
            site = SiteConfig(
                name=site_data.get("name", "unknown"),
                site_id=site_id,
                folder_path=site_data.get("folder_path", "docs_rag"),
                collection_name=site_data.get("collection_name", f"documents_{site_data.get('name', 'unknown')}"),
                enabled=site_data.get("enabled", True),
                description=site_data.get("description", ""),
                drive_id=site_data.get("drive_id"),
            )
            
            # Añadir TODOS los sitios para status reporting
            self.sites.append(site)
        
        enabled_count = len([s for s in self.sites if s.enabled])
        logger.info(f"✓ Configuración cargada: {len(self.sites)} sitios ({enabled_count} habilitados)")
    
    def _init_synchronizers(self) -> None:
        """Inicializa un SharePointSynchronizer por cada sitio habilitado"""
        for site in self.sites:
            if not site.enabled:
                logger.info(f"⏸️ Sitio deshabilitado (no sincronizar): {site.name}")
                continue
            try:
                # Crear carpeta local para este sitio
                site_folder = self.base_watch_folder / site.name
                site_folder.mkdir(parents=True, exist_ok=True)
                
                # Crear cliente SharePoint
                client = SharePointClient(
                    tenant_id=self.azure_tenant_id,
                    client_id=self.azure_client_id,
                    client_secret=self.azure_client_secret,
                    site_id=site.site_id,
                    drive_id=site.drive_id,
                    folder_path=site.folder_path,
                )
                
                # Crear sincronizador
                sync = SharePointSynchronizer(
                    client=client,
                    local_dir=str(site_folder),
                    delta_token_file=str(self.base_watch_folder / f".delta_{site.name}.txt"),
                )
                
                self.synchronizers[site.name] = {
                    "sync": sync,
                    "config": site,
                    "client": client,
                }
                
                logger.info(f"✓ Sincronizador inicializado: {site.name} → {site.collection_name}")
                
            except Exception as e:
                logger.error(f"Error inicializando sincronizador para {site.name}: {e}")
    
    def sync_all(self) -> List[SyncResult]:
        """
        Sincroniza todos los sitios (delta sync).
        
        Returns:
            Lista de archivos procesados con metadata de sitio/colección
        """
        logger.info(f"⏳ Iniciando sincronización de {len(self.synchronizers)} sitios...")
        all_results: List[SyncResult] = []
        
        for site_name, data in self.synchronizers.items():
            try:
                sync: SharePointSynchronizer = data["sync"]
                config: SiteConfig = data["config"]
                
                logger.info(f"📁 Sincronizando {site_name}...")
                changes = sync.sync()
                
                for change in changes:
                    result = SyncResult(
                        site_name=site_name,
                        collection_name=config.collection_name,
                        file_id=change.get("file_id", ""),
                        file_name=change.get("name", ""),
                        local_path=change.get("local_path", ""),
                        modified_at=change.get("modified_at"),
                        deleted=change.get("deleted", False),
                    )
                    all_results.append(result)
                
                if changes:
                    logger.info(f"  ✓ {site_name}: {len(changes)} cambios detectados")
                else:
                    logger.debug(f"  ✓ {site_name}: Sin cambios")
                    
            except Exception as e:
                logger.error(f"  ✗ Error sincronizando {site_name}: {e}")
                all_results.append(SyncResult(
                    site_name=site_name,
                    collection_name=data["config"].collection_name,
                    file_id="",
                    file_name="",
                    local_path="",
                    error=str(e),
                ))
        
        # Resumen
        successful = [r for r in all_results if not r.error and not r.deleted]
        deleted = [r for r in all_results if r.deleted]
        errors = [r for r in all_results if r.error]
        
        logger.info(
            f"✓ Sincronización completada: "
            f"{len(successful)} nuevos/modificados, "
            f"{len(deleted)} eliminados, "
            f"{len(errors)} errores"
        )
        
        return all_results
    
    def full_sync_all(self) -> List[SyncResult]:
        """
        Sincronización completa de todos los sitios (descarga todo).
        Usar solo en la primera ejecución o para reconstruir.
        """
        logger.info(f"🔄 Iniciando FULL sync de {len(self.synchronizers)} sitios...")
        all_results: List[SyncResult] = []
        
        for site_name, data in self.synchronizers.items():
            try:
                sync: SharePointSynchronizer = data["sync"]
                config: SiteConfig = data["config"]
                
                logger.info(f"📁 Full sync {site_name}...")
                downloaded = sync.full_sync()
                
                for item in downloaded:
                    result = SyncResult(
                        site_name=site_name,
                        collection_name=config.collection_name,
                        file_id=item.get("file_id", ""),
                        file_name=item.get("name", ""),
                        local_path=item.get("local_path", ""),
                    )
                    all_results.append(result)
                
                logger.info(f"  ✓ {site_name}: {len(downloaded)} archivos descargados")
                
            except Exception as e:
                logger.error(f"  ✗ Error en full sync de {site_name}: {e}")
        
        return all_results
    
    def get_status(self) -> Dict[str, Any]:
        """Devuelve estado de todos los sincronizadores"""
        return {
            "total_sites": len(self.sites),
            "active_synchronizers": len(self.synchronizers),
            "sites": [
                {
                    "name": site.name,
                    "collection": site.collection_name,
                    "enabled": site.enabled,
                    "folder": site.folder_path,
                }
                for site in self.sites
            ],
            "sync_interval": self.config.get("sync_settings", {}).get("interval_seconds", 300),
        }
    
    def get_collection_names(self) -> List[str]:
        """Devuelve lista de nombres de colecciones configuradas"""
        collections = [site.collection_name for site in self.sites]
        
        # Añadir colección compartida si está habilitada
        shared = self.config.get("shared_collection", {})
        if shared.get("enabled", False):
            collections.append(shared.get("name", "documents_Compartido"))
        
        return collections
    
    def get_permission_mapping(self) -> Dict[str, str]:
        """Devuelve mapeo de grupos Azure AD → colecciones"""
        return self.config.get("permission_mapping", {}).get("mappings", {})

# backend/app/integrations/sharepoint/client.py
"""
Cliente de Microsoft Graph API para SharePoint
Sincronización automática de documentos (robusto y con reintentos).

Mejoras clave:
- Reintentos exponenciales con backoff para 429/5xx y respeto de Retry-After
- Soporte opcional de drive_id además de site_id
- Listado recursivo con paginación (@odata.nextLink)
- Descarga en streaming con tamaño de chunk configurable
- Delta queries con manejo de paginación y token persistible
- Suscripciones (webhooks) con utilidades de renovación y listado
- Sesión HTTP reutilizable (requests.Session) y timeouts configurables
"""

from __future__ import annotations

import os
import time
import logging
from typing import List, Dict, Optional, Tuple, Iterable
from datetime import datetime, timedelta
from pathlib import Path

import requests
from msal import ConfidentialClientApplication

logger = logging.getLogger(__name__)


def _to_bool(v: Optional[str], default: bool = False) -> bool:
    if v is None:
        return default
    s = str(v).strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


class SharePointClient:
    """
    Cliente para Microsoft Graph API

    Funcionalidades:
    1) Autenticación con Azure AD (Client Credentials)
    2) Listar archivos de una carpeta (recursivo con paginación)
    3) Descargar archivos en streaming
    4) Delta queries (cambios incrementales)
    5) Suscripciones a webhooks (crear/renovar/eliminar/listar)
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        site_id: Optional[str] = None,
        folder_path: str = "Documents",
        *,
        drive_id: Optional[str] = None,
        request_timeout: int = 60,
        max_retries: int = 5,
        backoff_base: float = 0.5,
        chunk_size: int = 1024 * 1024,  # 1MB
    ):
        """
        Args:
            tenant_id: ID del tenant de Azure AD
            client_id: Application (client) ID
            client_secret: Client secret
            site_id: ID del sitio de SharePoint (si no usas drive_id)
            folder_path: Ruta de la carpeta a sincronizar (root relative)
            drive_id: ID del drive (opcional; si se proporciona, se prioriza frente a site_id)
            request_timeout: Timeout por request HTTP (segundos)
            max_retries: Reintentos para 429/5xx
            backoff_base: segundos base para backoff exponencial
            chunk_size: tamaño de chunk para descargas
        """
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.site_id = site_id
        self.folder_path = folder_path.strip("/ ")
        self.drive_id = drive_id

        # MSAL
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        self.app = ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=authority,
        )

        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None

        self.graph_url = "https://graph.microsoft.com/v1.0"

        # HTTP session
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self.request_timeout = int(request_timeout)
        self.max_retries = max(0, int(max_retries))
        self.backoff_base = float(backoff_base)
        self.chunk_size = int(chunk_size)

        logger.info(
            f"SharePoint Client inicializado "
            f"(site_id={site_id}, drive_id={drive_id}, folder='{self.folder_path}')"
        )

    # -------------------------
    # Auth
    # -------------------------

    def _get_access_token(self) -> str:
        if self.access_token and self.token_expires_at:
            if datetime.utcnow() < self.token_expires_at - timedelta(minutes=5):
                return self.access_token

        scopes = ["https://graph.microsoft.com/.default"]
        result = self.app.acquire_token_for_client(scopes=scopes)
        if "access_token" in result:
            self.access_token = result["access_token"]
            self.token_expires_at = datetime.utcnow() + timedelta(seconds=result.get("expires_in", 3600))
            return self.access_token

        error = result.get("error_description", result.get("error"))
        raise RuntimeError(f"Error obteniendo token de Graph: {error}")

    # -------------------------
    # Core request con reintentos
    # -------------------------

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        token = self._get_access_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("Content-Type", "application/json")
        timeout = kwargs.pop("timeout", self.request_timeout)

        url = endpoint if endpoint.startswith("http") else f"{self.graph_url}/{endpoint.lstrip('/')}"

        retries = 0
        while True:
            resp = self.session.request(method, url, headers=headers, timeout=timeout, **kwargs)
            status = resp.status_code

            if status < 400:
                return resp

            # Manejo de 401: intentar refrescar token una vez
            if status == 401 and retries < 1:
                logger.warning("401 no autorizado; refrescando token y reintentando...")
                self.access_token = None
                self.token_expires_at = None
                retries += 1
                continue

            # 429/5xx → backoff
            if status in (429, 500, 502, 503, 504) and retries < self.max_retries:
                wait = self._compute_backoff(resp, retries)
                logger.warning(f"{method} {url} → {status}; reintentando en {wait:.1f}s (try {retries+1}/{self.max_retries})")
                time.sleep(wait)
                retries += 1
                continue

            # Otros errores → raise
            try:
                err_json = resp.json()
            except Exception:
                err_json = {"text": resp.text[:500]}
            logger.error(f"Error Graph API {status}: {err_json}")
            resp.raise_for_status()

    def _compute_backoff(self, resp: requests.Response, retries: int) -> float:
        # Respeta Retry-After si existe
        ra = resp.headers.get("Retry-After")
        if ra:
            try:
                return max(float(ra), 0.1)
            except Exception:
                pass
        # Backoff exponencial con jitter ligero
        base = self.backoff_base * (2 ** retries)
        return base + (0.1 * retries)

    # -------------------------
    # Helpers de endpoint
    # -------------------------

    def _root_children_endpoint(self, path: Optional[str] = None) -> str:
        """
        Devuelve el endpoint para listar children de una ruta.
        Si drive_id está presente:
            - raíz:     /drives/{driveId}/root/children
            - con path: /drives/{driveId}/root:/path:/children
        Si no:
            - raíz:     /sites/{siteId}/drive/root/children
            - con path: /sites/{siteId}/drive/root:/path:/children
        """
        p = (path or self.folder_path).strip("/ ")
        if self.drive_id:
            if p:
                return f"drives/{self.drive_id}/root:/{p}:/children"
            return f"drives/{self.drive_id}/root/children"
        if not self.site_id:
            raise ValueError("Se requiere site_id o drive_id")
        if p:
            return f"sites/{self.site_id}/drive/root:/{p}:/children"
        return f"sites/{self.site_id}/drive/root/children"

    def _item_endpoint(self, item_id: str) -> str:
        if self.drive_id:
            return f"drives/{self.drive_id}/items/{item_id}"
        if not self.site_id:
            raise ValueError("Se requiere site_id o drive_id")
        return f"sites/{self.site_id}/drive/items/{item_id}"

    # -------------------------
    # Archivos
    # -------------------------

    def _iter_children(self, endpoint: str) -> Iterable[Dict]:
        """
        Itera sobre todos los children de un endpoint con paginación.
        """
        next_url: Optional[str] = endpoint
        while next_url:
            if next_url.startswith("http"):
                resp = self._request("GET", next_url)
            else:
                resp = self._request("GET", endpoint if next_url == endpoint else next_url)

            data = resp.json()
            for item in data.get("value", []):
                yield item

            next_url = data.get("@odata.nextLink")

    def list_files(self, folder_path: Optional[str] = None, recursive: bool = True) -> List[Dict]:
        """
        Lista archivos de una carpeta SharePoint (con paginación y recursión).

        Returns:
            List[Dict] con metadatos de archivos.
        """
        base_path = (folder_path or self.folder_path).strip("/ ")
        endpoint = self._root_children_endpoint(base_path)
        logger.info(f"Listando archivos en: {base_path or '/'} (recursive={recursive})")

        files: List[Dict] = []
        stack: List[Tuple[str, Optional[str]]] = [(base_path, None)]  # (path, item_id no usado aquí)

        # Para evitar excesiva recursión, iteramos manualmente
        while stack:
            current_path, _ = stack.pop()
            ep = self._root_children_endpoint(current_path)
            for item in self._iter_children(ep):
                if "file" in item:
                    files.append(self._map_item_to_file(item))
                elif recursive and "folder" in item:
                    subpath = f"{current_path}/{item['name']}".strip("/ ")
                    stack.append((subpath, item.get("id")))

        logger.info(f"✓ Encontrados {len(files)} archivos")
        return files

    def _map_item_to_file(self, item: Dict) -> Dict:
        return {
            "id": item["id"],
            "name": item["name"],
            "size": item.get("size"),
            "web_url": item.get("webUrl"),
            "download_url": item.get("@microsoft.graph.downloadUrl"),
            "created_at": item.get("createdDateTime"),
            "modified_at": item.get("lastModifiedDateTime"),
            "path": item.get("parentReference", {}).get("path", ""),
            "mime_type": item.get("file", {}).get("mimeType"),
            "hash": item.get("file", {}).get("hashes", {}).get("quickXorHash"),
        }

    def download_file(self, file_id: str, destination: str) -> str:
        """
        Descarga un archivo de SharePoint usando la URL temporal de descarga.
        """
        item = self.get_file_metadata(file_id)
        dl = item.get("@microsoft.graph.downloadUrl")
        if not dl:
            raise RuntimeError(f"No se pudo obtener downloadUrl para {file_id}")

        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Streaming con reintentos
        retries = 0
        while True:
            resp = self.session.get(dl, stream=True, timeout=self.request_timeout)
            if resp.status_code < 400:
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=self.chunk_size):
                        if chunk:
                            f.write(chunk)
                logger.info(f"✓ Archivo descargado: {dest}")
                return str(dest)

            if resp.status_code in (429, 500, 502, 503, 504) and retries < self.max_retries:
                wait = self._compute_backoff(resp, retries)
                logger.warning(f"download_file {file_id} → {resp.status_code}; retry en {wait:.1f}s")
                time.sleep(wait)
                retries += 1
                continue

            try:
                err = resp.json()
            except Exception:
                err = {"text": resp.text[:500]}
            logger.error(f"Fallo al descargar {file_id}: {err}")
            resp.raise_for_status()

    def get_file_metadata(self, file_id: str) -> Dict:
        """Obtiene metadata completa de un archivo."""
        endpoint = self._item_endpoint(file_id)
        resp = self._request("GET", endpoint)
        return resp.json()

    # -------------------------
    # Delta queries (cambios)
    # -------------------------

    def get_changes(self, delta_token: Optional[str] = None) -> Tuple[List[Dict], Optional[str]]:
        """
        Obtiene cambios desde la última sincronización.

        Returns:
            (lista_de_cambios, nuevo_delta_token)
        """
        logger.info("Consultando cambios (delta query)...")

        if delta_token and delta_token.startswith("http"):
            endpoint = delta_token
        else:
            base = f"drives/{self.drive_id}" if self.drive_id else f"sites/{self.site_id}/drive"
            # Delta sobre la ruta
            if self.folder_path:
                endpoint = f"{base}/root:/{self.folder_path}:/delta"
            else:
                endpoint = f"{base}/root/delta"

        items: List[Dict] = []
        next_url: Optional[str] = endpoint
        delta_link: Optional[str] = None

        while next_url:
            resp = self._request("GET", next_url)
            data = resp.json()

            for it in data.get("value", []):
                if "file" in it or "deleted" in it:
                    items.append(
                        {
                            "id": it.get("id"),
                            "name": it.get("name"),
                            "modified_at": it.get("lastModifiedDateTime"),
                            "deleted": it.get("deleted") is not None,
                            "item": it,
                        }
                    )

            next_url = data.get("@odata.nextLink")
            delta_link = data.get("@odata.deltaLink") or delta_link

        logger.info(f"✓ Cambios obtenidos: {len(items)}")
        return items, delta_link

    # -------------------------
    # Webhooks (suscripciones)
    # -------------------------

    def create_subscription(
        self,
        notification_url: str,
        resource_path: Optional[str] = None,
        expiration_hours: int = 24,
        client_state: Optional[str] = None,
    ) -> Dict:
        """
        Crea suscripción a webhooks de SharePoint.
        `resource_path` puede ser:
          - si drive_id: f"/drives/{drive_id}/root"
          - si site_id : f"/sites/{site_id}/drive/root"
          - puedes añadir `:/{folder_path}` para una carpeta concreta.
        """
        if not (self.drive_id or self.site_id):
            raise ValueError("Se requiere site_id o drive_id para crear suscripciones")

        if resource_path:
            resource = resource_path
        else:
            if self.drive_id:
                resource = f"/drives/{self.drive_id}/root"
                if self.folder_path:
                    resource = f"{resource}:/{self.folder_path}"
            else:
                resource = f"/sites/{self.site_id}/drive/root"
                if self.folder_path:
                    resource = f"{resource}:/{self.folder_path}"

        expiration = datetime.utcnow() + timedelta(hours=expiration_hours)
        body = {
            "changeType": "updated,created,deleted",
            "notificationUrl": notification_url,
            "resource": resource,
            "expirationDateTime": expiration.isoformat() + "Z",
            "clientState": client_state or self._generate_client_state(),
        }

        resp = self._request("POST", "subscriptions", json=body)
        sub = resp.json()
        logger.info(f"✓ Suscripción creada: {sub.get('id')} (expira {sub.get('expirationDateTime')})")
        return sub

    def renew_subscription(self, subscription_id: str, hours: int = 24) -> Dict:
        expiration = datetime.utcnow() + timedelta(hours=hours)
        resp = self._request(
            "PATCH",
            f"subscriptions/{subscription_id}",
            json={"expirationDateTime": expiration.isoformat() + "Z"},
        )
        logger.info(f"✓ Suscripción {subscription_id} renovada")
        return resp.json()

    def delete_subscription(self, subscription_id: str):
        self._request("DELETE", f"subscriptions/{subscription_id}")
        logger.info(f"✓ Suscripción {subscription_id} eliminada")

    def list_subscriptions(self) -> List[Dict]:
        resp = self._request("GET", "subscriptions")
        return resp.json().get("value", [])

    @staticmethod
    def _generate_client_state() -> str:
        import secrets

        return secrets.token_urlsafe(32)

    @staticmethod
    def validate_webhook(*, client_state: str, expected_client_state: str) -> bool:
        """
        Valida notificación de webhook comparando clientState.
        (Graph no firma el cuerpo por defecto; si necesitas firma,
         colócala a nivel de reverse proxy.)
        """
        ok = client_state == expected_client_state
        if not ok:
            logger.warning("clientState no coincide en webhook")
        return ok


# ============================================
# SINCRONIZADOR AUTOMÁTICO
# ============================================

class SharePointSynchronizer:
    """
    Sincronizador automático de SharePoint → carpeta local.

    - Usa delta queries para cambios incrementales
    - Persiste el delta token en un fichero
    """

    def __init__(
        self,
        client: SharePointClient,
        local_dir: str,
        delta_token_file: str = "./sharepoint_delta.txt",
    ):
        self.client = client
        self.local_dir = Path(local_dir)
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self.delta_token_file = Path(delta_token_file)
        logger.info(f"Sincronizador inicializado: {self.local_dir}")

    def _load_delta_token(self) -> Optional[str]:
        if self.delta_token_file.exists():
            return self.delta_token_file.read_text(encoding="utf-8").strip() or None
        return None

    def _save_delta_token(self, token: str):
        self.delta_token_file.write_text(token or "", encoding="utf-8")

    def sync(self) -> List[Dict]:
        """
        Sincroniza cambios desde SharePoint.
        Descarga nuevos/actualizados y reporta eliminados (no borra local).
        """
        logger.info("Iniciando sincronización incremental...")
        delta_token = self._load_delta_token()
        changes, new_token = self.client.get_changes(delta_token)

        processed: List[Dict] = []
        for ch in changes:
            name = ch.get("name") or "unknown"
            if ch.get("deleted"):
                logger.info(f"Eliminado en origen: {name} (id={ch.get('id')})")
                # Aquí podrías eliminar del índice/vector DB si procede
                continue

            try:
                local_path = self.local_dir / name
                self.client.download_file(ch["id"], str(local_path))
                processed.append(
                    {
                        "file_id": ch["id"],
                        "name": name,
                        "local_path": str(local_path),
                        "modified_at": ch.get("modified_at"),
                    }
                )
            except Exception as e:
                logger.error(f"Error procesando {name}: {e}")

        if new_token:
            self._save_delta_token(new_token)
            logger.info("Delta token actualizado")

        logger.info(f"✓ Sincronización completada: {len(processed)} archivos descargados/actualizados")
        return processed

    def full_sync(self) -> List[Dict]:
        """
        Sincronización completa: lista y descarga todo el contenido de la carpeta base.
        """
        logger.info("Sincronización completa (full sync)...")
        files = self.client.list_files()
        downloaded: List[Dict] = []
        for f in files:
            try:
                local_path = self.local_dir / f["name"]
                self.client.download_file(f["id"], str(local_path))
                downloaded.append({"file_id": f["id"], "name": f["name"], "local_path": str(local_path)})
            except Exception as e:
                logger.error(f"Error descargando {f['name']}: {e}")

        logger.info(f"✓ Descargados {len(downloaded)} archivos")
        return downloaded


# ============================================
# EJEMPLO DE USO
# ============================================

if __name__ == "__main__":
    # Variables de entorno recomendadas
    TENANT = os.getenv("AZURE_TENANT_ID", "")
    CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
    CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
    SITE_ID = os.getenv("SHAREPOINT_SITE_ID", "")
    DRIVE_ID = os.getenv("SHAREPOINT_DRIVE_ID")  # opcional
    FOLDER = os.getenv("SHAREPOINT_FOLDER_PATH", "Documents/RAG")

    client = SharePointClient(
        tenant_id=TENANT,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        site_id=SITE_ID or None,
        drive_id=DRIVE_ID or None,
        folder_path=FOLDER,
        request_timeout=int(os.getenv("GRAPH_TIMEOUT", "60")),
        max_retries=int(os.getenv("GRAPH_MAX_RETRIES", "5")),
        backoff_base=float(os.getenv("GRAPH_BACKOFF_BASE", "0.5")),
    )

    # Listar
    flist = client.list_files()
    print(f"Archivos encontrados: {len(flist)}")

    # Sincronizador
    sync = SharePointSynchronizer(client=client, local_dir="./data/sharepoint")
    # Primera sincronización (full)
    sync.full_sync()
    # Incrementales
    sync.sync()

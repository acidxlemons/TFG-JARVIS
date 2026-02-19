"""
Add SharePoint Site to RAG System.

Interactive script to add a new SharePoint site to the RAG configuration.
Creates the Qdrant collection and updates sharepoint_sites.json.

Usage:
    python scripts/add_sharepoint_site.py
    python scripts/add_sharepoint_site.py --name "Ejemplo" --site-url "https://your-tenant.sharepoint.com/sites/Ejemplo"
"""

import os
import sys
import json
import argparse
import requests
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configuration
CONFIG_PATH = "config/sharepoint_sites.json"
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")


def load_config() -> dict:
    """Load current SharePoint sites configuration."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "description": "Configuracion de sitios SharePoint para sincronizacion RAG",
            "sync_settings": {
                "interval_seconds": 300,
                "full_sync_on_startup": True,
                "delete_local_on_remote_delete": True
            },
            "sites": [],
            "permission_mapping": {"mappings": {}}
        }


def save_config(config: dict):
    """Save configuration."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    print(f"[+] Configuracion guardada en {CONFIG_PATH}")


def create_qdrant_collection(collection_name: str, vector_size: int = 384):
    """Create a new Qdrant collection."""
    try:
        # Check if exists
        r = requests.get(f"{QDRANT_URL}/collections/{collection_name}", timeout=10)
        if r.status_code == 200:
            print(f"[*] Coleccion '{collection_name}' ya existe")
            return True
        
        # Create collection
        payload = {
            "vectors": {
                "size": vector_size,
                "distance": "Cosine"
            }
        }
        r = requests.put(
            f"{QDRANT_URL}/collections/{collection_name}",
            json=payload,
            timeout=30
        )
        
        if r.status_code in [200, 201]:
            print(f"[+] Coleccion '{collection_name}' creada en Qdrant")
            return True
        else:
            print(f"[!] Error creando coleccion: {r.status_code} - {r.text}")
            return False
            
    except Exception as e:
        print(f"[!] Error conectando a Qdrant: {e}")
        return False


def get_existing_sites(config: dict) -> list:
    """Get list of existing site names."""
    return [site["name"] for site in config.get("sites", [])]


def add_site_interactive():
    """Interactive mode to add a new site."""
    print("=" * 60)
    print("  AÑADIR NUEVO SITIO SHAREPOINT AL SISTEMA RAG")
    print("=" * 60)
    print()
    
    config = load_config()
    existing = get_existing_sites(config)
    
    if existing:
        print(f"[*] Sitios existentes: {', '.join(existing)}")
        print()
    
    # Get site name
    while True:
        name = input("Nombre del sitio (ej: Compras, RRHH): ").strip()
        if not name:
            print("  [!] El nombre no puede estar vacio")
            continue
        if name in existing:
            print(f"  [!] El sitio '{name}' ya existe")
            continue
        break
    
    # Get site ID
    print()
    print("Para obtener el site_id:")
    print("  1. Ve a SharePoint y abre el sitio")
    print("  2. Copia la URL (ej: https://tu-tenant.sharepoint.com/sites/NombreSitio)")
    print("  3. Usa Graph Explorer para obtener el ID del sitio")
    print("  O dejalo vacio y lo configuras manualmente despues")
    print()
    site_id = input("Site ID (o URL del sitio): ").strip()
    
    # Normalize collection name
    collection_name = f"documents_{name.upper().replace(' ', '_').replace('-', '_')}"
    print(f"[*] Nombre de coleccion Qdrant: {collection_name}")
    
    # Get folder path
    folder_path = input("Carpeta dentro del sitio (dejar vacio para raiz): ").strip()
    
    # Azure AD groups
    print()
    print("Grupos de Azure AD que tendran acceso (separados por coma)")
    print("  Ej: Compras-Members, Compras Members")
    groups_input = input("Grupos: ").strip()
    azure_groups = [g.strip() for g in groups_input.split(",") if g.strip()]
    
    # Confirm
    print()
    print("=" * 60)
    print("RESUMEN:")
    print(f"  Nombre: {name}")
    print(f"  Site ID: {site_id or '(configurar manualmente)'}")
    print(f"  Carpeta: {folder_path or '(raiz)'}")
    print(f"  Coleccion: {collection_name}")
    print(f"  Grupos: {azure_groups or ['(ninguno - acceso global)']}")
    print("=" * 60)
    
    confirm = input("¿Añadir este sitio? (s/n): ").strip().lower()
    if confirm != "s":
        print("[*] Cancelado")
        return
    
    # Create Qdrant collection
    print()
    if not create_qdrant_collection(collection_name):
        print("[!] No se pudo crear la coleccion. Continuando de todas formas...")
    
    # Add to config
    new_site = {
        "name": name,
        "site_id": site_id,
        "folder_path": folder_path,
        "collection_name": collection_name,
        "enabled": True,
        "description": f"Site {name} - añadido automaticamente",
        "azure_groups": azure_groups
    }
    
    config["sites"].append(new_site)
    
    # Add group mappings
    for group in azure_groups:
        if "permission_mapping" not in config:
            config["permission_mapping"] = {"mappings": {}}
        if group not in config["permission_mapping"]["mappings"]:
            config["permission_mapping"]["mappings"][group] = collection_name
    
    # Save
    save_config(config)
    
    print()
    print("=" * 60)
    print("[+] SITIO AÑADIDO CORRECTAMENTE")
    print("=" * 60)
    print()
    print("Proximos pasos:")
    print(f"  1. Si no especificaste site_id, editalo en {CONFIG_PATH}")
    print("  2. Reinicia el indexer: docker compose restart rag-indexer")
    print("  3. El indexer comenzara a sincronizar el nuevo sitio")
    print()


def add_site_cli(args):
    """CLI mode to add a site."""
    config = load_config()
    
    name = args.name
    collection_name = args.collection or f"documents_{name.upper().replace(' ', '_')}"
    azure_groups = args.groups.split(",") if args.groups else []
    
    # Check if exists
    existing = get_existing_sites(config)
    if name in existing:
        print(f"[!] El sitio '{name}' ya existe")
        sys.exit(1)
    
    # Create Qdrant collection
    if not args.skip_qdrant:
        create_qdrant_collection(collection_name)
    
    # Add site
    new_site = {
        "name": name,
        "site_id": args.site_id or "",
        "folder_path": args.folder or "",
        "collection_name": collection_name,
        "enabled": True,
        "description": args.description or f"Site {name}",
        "azure_groups": azure_groups
    }
    
    config["sites"].append(new_site)
    
    # Add group mappings
    for group in azure_groups:
        if "permission_mapping" not in config:
            config["permission_mapping"] = {"mappings": {}}
        if group not in config["permission_mapping"]["mappings"]:
            config["permission_mapping"]["mappings"][group] = collection_name
    
    save_config(config)
    print(f"[+] Sitio '{name}' añadido con coleccion '{collection_name}'")


def main():
    parser = argparse.ArgumentParser(description="Add SharePoint site to RAG")
    parser.add_argument("--name", "-n", help="Site name")
    parser.add_argument("--site-id", "-s", help="SharePoint site ID")
    parser.add_argument("--folder", "-f", help="Folder path within site")
    parser.add_argument("--collection", "-c", help="Qdrant collection name")
    parser.add_argument("--groups", "-g", help="Azure AD groups (comma-separated)")
    parser.add_argument("--description", "-d", help="Site description")
    parser.add_argument("--skip-qdrant", action="store_true", help="Skip Qdrant collection creation")
    
    args = parser.parse_args()
    
    if args.name:
        add_site_cli(args)
    else:
        add_site_interactive()


if __name__ == "__main__":
    main()

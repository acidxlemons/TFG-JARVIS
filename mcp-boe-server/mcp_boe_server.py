"""
MCP Server para el BOE (Boletín Oficial del Estado)

Expone la API de Datos Abiertos del BOE como herramientas MCP
para que cualquier cliente AI pueda consultar legislación española.

Doc API BOE: https://www.boe.es/datosabiertos/api/api.php
"""

from fastmcp import FastMCP
from boe_connector import BoeConnector
from typing import Optional

# Crear servidor MCP
mcp = FastMCP("BOE Server 🇪🇸")

# Instancia del conector
boe = BoeConnector()


@mcp.tool
def get_boe_summary(date: Optional[str] = None) -> list:
    """
    Obtiene el sumario del BOE para una fecha dada.
    
    Args:
        date: Fecha en formato YYYYMMDD. Si no se especifica, usa la fecha de hoy.
        
    Returns:
        Lista de disposiciones publicadas con id, título, departamento, enlace y PDF.
        
    Example:
        get_boe_summary("20240115")  # Sumario del 15 de enero de 2024
        get_boe_summary()             # Sumario de hoy
    """
    return boe.get_summary(date)


@mcp.tool
def search_legislation(query: str, days_back: int = 7) -> list:
    """
    Busca legislación reciente por palabras clave en los sumarios del BOE.
    
    Args:
        query: Palabras clave a buscar (ej: "protección de datos", "impuestos")
        days_back: Número de días hacia atrás para buscar (por defecto 7)
        
    Returns:
        Lista de resultados con título, enlace, resumen y fecha.
        
    Example:
        search_legislation("inteligencia artificial", 30)
        search_legislation("subvenciones")
    """
    return boe.search_legislation(query, days_back)


@mcp.tool
def get_law_text(law_id: str) -> dict:
    """
    Obtiene el texto completo de una ley consolidada.
    
    Args:
        law_id: Identificador BOE de la ley (ej: BOE-A-2018-16673 para LOPD)
        
    Returns:
        Diccionario con law_id, title, text, word_count y link.
        
    Example:
        get_law_text("BOE-A-2018-16673")  # Ley de Protección de Datos
        get_law_text("BOE-A-1978-31229")  # Constitución Española
    """
    return boe.get_law_text(law_id)


@mcp.tool
def get_law_metadata(law_id: str) -> dict:
    """
    Obtiene metadatos de una ley: título, rango, fecha de publicación y estado.
    
    Args:
        law_id: Identificador BOE de la ley
        
    Returns:
        Diccionario con law_id, title, rango, fecha_publicacion, estado y link.
        
    Example:
        get_law_metadata("BOE-A-2015-11430")  # Estatuto de los Trabajadores
    """
    return boe.get_law_metadata(law_id)


@mcp.tool
def get_law_analysis(law_id: str) -> dict:
    """
    Obtiene el análisis jurídico de una ley: qué leyes modifica y cuáles la han modificado.
    
    Args:
        law_id: Identificador BOE de la ley
        
    Returns:
        Diccionario con law_id, modifies (leyes que modifica) y modified_by (leyes que la modifican).
        
    Example:
        get_law_analysis("BOE-A-2018-16673")  # Ver qué modifica la LOPDGDD
    """
    return boe.get_law_analysis(law_id)


@mcp.tool
def get_subjects() -> list:
    """
    Obtiene la lista de materias/categorías disponibles en el BOE.
    
    Returns:
        Lista de diccionarios con code y name de cada materia.
        
    Example:
        get_subjects()  # Lista todas las categorías temáticas
    """
    return boe.get_subjects()


@mcp.tool
def resolve_law_name(law_name: str) -> dict:
    """
    Resuelve un nombre común de ley a su identificador BOE.
    
    Nombres soportados: LOPD, LOPDGDD, Constitución, Estatuto de los Trabajadores (ET),
    LPAC, LRJSP, LCSP, Código Civil, Código Penal, LGT, IRPF.
    
    Args:
        law_name: Nombre común o abreviatura de la ley
        
    Returns:
        Diccionario con el nombre, id BOE y enlace, o null si no se encuentra.
        
    Example:
        resolve_law_name("LOPD")         # -> BOE-A-2018-16673
        resolve_law_name("constitución") # -> BOE-A-1978-31229
    """
    law_id = boe.resolve_law_id(law_name)
    if law_id:
        return {
            "name": law_name,
            "law_id": law_id,
            "link": f"https://www.boe.es/buscar/act.php?id={law_id}"
        }
    return {"error": f"No se encontró ley con el nombre '{law_name}'", "name": law_name}


if __name__ == "__main__":
    import sys
    
    # ==========================================================================
    # MODO DE EJECUCIÓN
    # ==========================================================================
    # 
    # OPCIÓN 1: HTTP Transport (para OpenWebUI)
    # -----------------------------------------
    # Ejecutar como servidor HTTP que OpenWebUI puede consumir directamente.
    # En OpenWebUI: Admin Panel → Settings → External Tools → Añadir MCP Streamable HTTP
    # URL: http://localhost:8000
    #
    # OPCIÓN 2: STDIO Transport (para Claude Desktop)
    # ------------------------------------------------
    # El modo clásico para clientes como Claude Desktop que usan stdio.
    # Configurar en claude_desktop_config.json
    #
    # ==========================================================================
    
    # Por defecto: HTTP para OpenWebUI
    # Usar --stdio para modo Claude Desktop
    
    if "--stdio" in sys.argv:
        # Modo STDIO (Claude Desktop, etc.)
        print("[BOE MCP] Iniciando en modo STDIO...", file=sys.stderr)
        mcp.run()
    else:
        # Modo HTTP (OpenWebUI)
        port = 8010  # Puerto 8010 para evitar conflicto con rag-backend (8000)
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        
        print(f"[BOE MCP] Server iniciando en http://localhost:{port}")
        print(f"   Anadir en OpenWebUI: Admin Panel -> Settings -> External Tools")
        print(f"   Type: MCP Streamable HTTP | URL: http://localhost:{port}")
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)


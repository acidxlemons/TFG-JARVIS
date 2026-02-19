"""
backend/app/integrations/boe_connector.py

Conector para la API de Datos Abiertos del BOE (Boletín Oficial del Estado).
Doc: https://www.boe.es/datosabiertos/api/api.php
"""

import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class BoeConnector:
    """
    Conector para buscar legislación en el BOE.
    Utiliza la API de sumarios y búsqueda del BOE.
    """
    
    BASE_URL = "https://www.boe.es/datosabiertos/api/api.php"
    
    def __init__(self):
        pass

    def get_summary(self, date: Optional[str] = None) -> List[Dict]:
        """
        Obtiene el sumario del BOE para una fecha dada (YYYYMMDD).
        Si no se da fecha, usa la de hoy.
        """
        if not date:
            date = datetime.now().strftime("%Y%m%d")
            
        try:
            # URL correcta para XML: https://boe.es/datosabiertos/api/boe/sumario/YYYYMMDD
            # Requiere header Accept: application/xml
            url = f"https://boe.es/datosabiertos/api/boe/sumario/{date}"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "application/xml"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Parsear XML
            root = ET.fromstring(response.content)
            
            items = []
            
            # Navegar XML: diario > seccion > departamento > item
            # Estructura típica:
            # <diario>
            #   <seccion nombre="I. Disposiciones generales">
            #     <departamento nombre="MINISTERIO DE...">
            #       <item id="BOE-A-202X-XXXX">
            #         <titulo>...</titulo>
            #         <url_pdf>...</url_pdf>
            
            for seccion in root.findall(".//seccion"):
                sec_name = seccion.get("nombre", "")
                # Permitir I (Disposiciones), II (Autoridades), III (Otras) y V (Anuncios)
                # Si es un día sin leyes (o futuro/simulado), al menos mostrar anuncios.
                if not any(sec_name.startswith(prefix) for prefix in ["I", "V"]):
                    # Nota: II y III empiezan por 'I' (II, III), así que startswith("I") ya las cubre.
                    # Pero 'V' necesita ser añadida explícitamente.
                    # Ajustamos para ser más permisivos.
                    pass
                
                # O mejor, simplemente incluimos todo lo relevante.
                # En la prueba vimos: I, II, III, V.
                valid_sections = ["I", "II", "III", "V"]
                if not any(sec_name.startswith(p) for p in valid_sections):
                    continue
                    
                for dep in seccion.findall("departamento"):
                    dep_name = dep.get("nombre", "")
                    
                    for item in dep.findall("item"):
                        ident = item.get("id", "")
                        titulo = item.find("titulo").text if item.find("titulo") is not None else ""
                        url_pdf = item.find("url_pdf").text if item.find("url_pdf") is not None else ""
                        url_html = item.find("url_html").text if item.find("url_html") is not None else ""
                        
                        items.append({
                            "id": ident,
                            "title": titulo,
                            "department": dep_name,
                            "link": f"https://www.boe.es{url_html}" if url_html.startswith("/") else url_html,
                            "pdf": f"https://www.boe.es{url_pdf}" if url_pdf.startswith("/") else url_pdf,
                            "date": date
                        })
            
            return items
            
        except Exception as e:
            logger.error(f"Error fetching BOE summary: {e}")
            return []

    def search_legislation(self, query: str, days_back: int = 7) -> List[Dict]:
        """
        Busca legislación buscando keywords en los sumarios de los últimos días.
        La API de búsqueda web del BOE no funciona consistentemente con scraping,
        pero los sumarios diarios sí son accesibles y fiables.
        """
        from datetime import timedelta
        
        found = []
        query_lower = query.lower()
        start_date = datetime.now()
        
        logger.info(f"Buscando '{query}' en sumarios de los últimos {days_back} días...")
        
        for i in range(days_back):
            date = start_date - timedelta(days=i)
            date_str = date.strftime("%Y%m%d")
            
            try:
                url = f"https://boe.es/datosabiertos/api/boe/sumario/{date_str}"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "application/xml"
                }
                
                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code != 200:
                    continue
                    
                root = ET.fromstring(response.content)
                
                for item in root.findall(".//item"):
                    titulo_el = item.find("titulo")
                    titulo = titulo_el.text if titulo_el is not None and titulo_el.text else ""
                    
                    # Buscar en título
                    if query_lower in titulo.lower():
                        url_html = item.find("url_html")
                        url_html_text = url_html.text if url_html is not None and url_html.text else ""
                        
                        found.append({
                            "title": titulo,
                            "link": f"https://www.boe.es{url_html_text}" if url_html_text.startswith("/") else url_html_text,
                            "summary": f"Publicado el {date_str[:4]}-{date_str[4:6]}-{date_str[6:]}",
                            "source": "BOE Sumario",
                            "date": date_str
                        })
                        
                        # Limitar resultados
                        if len(found) >= 20:
                            return found
                            
            except Exception as e:
                logger.warning(f"Error procesando sumario {date_str}: {e}")
                continue
        
        logger.info(f"Encontrados {len(found)} resultados para '{query}'")
        return found

    # ========== FASE 1: Texto Completo de Leyes ==========
    
    # Mapeo de nombres comunes a IDs del BOE
    LAW_MAPPINGS = {
        # Protección de Datos
        "lopd": "BOE-A-2018-16673",
        "lopdgdd": "BOE-A-2018-16673",
        "ley protección de datos": "BOE-A-2018-16673",
        # Constitución
        "constitución": "BOE-A-1978-31229",
        "constitucion": "BOE-A-1978-31229",
        "ce": "BOE-A-1978-31229",
        # Laboral
        "estatuto de los trabajadores": "BOE-A-2015-11430",
        "et": "BOE-A-2015-11430",
        # Administrativo
        "lpac": "BOE-A-2015-10565",
        "procedimiento administrativo": "BOE-A-2015-10565",
        "lrjsp": "BOE-A-2015-10566",
        # Contratos
        "lcsp": "BOE-A-2017-12902",
        "ley de contratos": "BOE-A-2017-12902",
        # Códigos
        "código civil": "BOE-A-1889-4763",
        "codigo civil": "BOE-A-1889-4763",
        "código penal": "BOE-A-1995-25444",
        "codigo penal": "BOE-A-1995-25444",
        # Tributario
        "lgt": "BOE-A-2003-23186",
        "irpf": "BOE-A-2006-20764",
    }

    def resolve_law_id(self, law_name: str) -> Optional[str]:
        """Resuelve nombre común a ID BOE."""
        normalized = law_name.lower().strip()
        if normalized in self.LAW_MAPPINGS:
            return self.LAW_MAPPINGS[normalized]
        for key, boe_id in self.LAW_MAPPINGS.items():
            if key in normalized or normalized in key:
                return boe_id
        return None

    def get_law_text(self, law_id: str) -> Dict:
        """Obtiene texto completo de una ley consolidada."""
        url = f"https://boe.es/datosabiertos/api/legislacion-consolidada/id/{law_id}/texto"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/xml"}
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 404:
                return {"error": "Ley no encontrada", "law_id": law_id}
            response.raise_for_status()
            root = ET.fromstring(response.content)
            
            # Obtener título de metadatos primero (más confiable)
            meta_url = f"https://boe.es/datosabiertos/api/legislacion-consolidada/id/{law_id}/metadatos"
            try:
                meta_resp = requests.get(meta_url, headers=headers, timeout=10)
                meta_root = ET.fromstring(meta_resp.content)
                titulo_el = meta_root.find(".//titulo")
                titulo = titulo_el.text if titulo_el is not None and titulo_el.text else law_id
            except:
                titulo = law_id
            
            # Extraer texto de los bloques/versiones/párrafos
            texto_parts = []
            
            # Buscar todos los párrafos <p>
            for p in root.findall(".//p"):
                if p.text:
                    texto_parts.append(p.text.strip())
                # También el texto dentro de subelementos
                full_text = ET.tostring(p, encoding='unicode', method='text')
                if full_text and full_text.strip() and full_text.strip() not in texto_parts:
                    texto_parts.append(full_text.strip())
            
            # Si no hay párrafos, buscar texto directo en bloques
            if not texto_parts:
                for bloque in root.findall(".//bloque"):
                    bloque_text = ET.tostring(bloque, encoding='unicode', method='text')
                    if bloque_text and bloque_text.strip():
                        texto_parts.append(bloque_text.strip())
            
            texto_completo = "\n\n".join(texto_parts)
            
            return {
                "law_id": law_id,
                "title": titulo,
                "text": texto_completo,
                "word_count": len(texto_completo.split()),
                "link": f"https://www.boe.es/buscar/act.php?id={law_id}"
            }
        except Exception as e:
            logger.error(f"Error obteniendo ley {law_id}: {e}")
            return {"error": str(e), "law_id": law_id}

    def get_law_metadata(self, law_id: str) -> Dict:
        """Obtiene metadatos de una ley."""
        url = f"https://boe.es/datosabiertos/api/legislacion-consolidada/id/{law_id}/metadatos"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/xml"}
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            
            def get_text(xpath):
                el = root.find(xpath)
                return el.text if el is not None else None
            
            return {
                "law_id": law_id,
                "title": get_text(".//titulo"),
                "rango": get_text(".//rango"),
                "fecha_publicacion": get_text(".//fecha_publicacion"),
                "estado": get_text(".//estado_consolidacion"),
                "link": f"https://www.boe.es/buscar/act.php?id={law_id}"
            }
        except Exception as e:
            return {"error": str(e), "law_id": law_id}

    def get_subjects(self) -> List[Dict]:
        """Obtiene lista de materias/categorías."""
        url = "https://boe.es/datosabiertos/api/datos-auxiliares/materias"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/xml"}
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            return [{"code": i.find("codigo").text, "name": i.find("nombre").text} 
                    for i in root.findall(".//item") if i.find("codigo") is not None]
        except Exception as e:
            logger.error(f"Error obteniendo materias: {e}")
            return []

    def get_law_analysis(self, law_id: str) -> Dict:
        """Obtiene análisis jurídico: qué modifica y qué la modifica."""
        url = f"https://boe.es/datosabiertos/api/legislacion-consolidada/id/{law_id}/analisis"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/xml"}
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            
            def parse_relations(parent_tag):
                rels = []
                # Find all elements like <anterior> or <posterior>
                for r in root.findall(f".//{parent_tag}"):
                    id_norma = r.find("id_norma")
                    relacion = r.find("relacion")
                    texto = r.find("texto")
                    
                    if id_norma is not None and id_norma.text:
                        rels.append({
                            "id": id_norma.text,
                            "relation": relacion.text if relacion is not None else None,
                            "description": texto.text if texto is not None else None
                        })
                return rels
            
            return {
                "law_id": law_id,
                "modifies": parse_relations("anterior"),
                "modified_by": parse_relations("posterior")
            }
        except Exception as e:
            logger.error(f"Error get_law_analysis: {e}")
            return {"error": str(e), "law_id": law_id}

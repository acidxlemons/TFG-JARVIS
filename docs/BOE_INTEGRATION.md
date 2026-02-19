# 📜 Integración BOE (Boletín Oficial del Estado)

**Proyecto**: TFG - Universidad Rey Juan Carlos  
**Versión**: 1.0  
**Última actualización**: Enero 2026

---

## 📖 Índice

1. [Introducción](#1-introducción)
2. [API Open Data del BOE](#2-api-open-data-del-boe)
3. [Arquitectura de Integración](#3-arquitectura-de-integración)
4. [Implementación Técnica](#4-implementación-técnica)
5. [Flujo de Detección de Intención](#5-flujo-de-detección-de-intención)
6. [Estrategias de Búsqueda](#6-estrategias-de-búsqueda)
7. [Manejo de Errores y Resilencia](#7-manejo-de-errores-y-resilencia)
8. [Ejemplos de Uso](#8-ejemplos-de-uso)
9. [Consideraciones de Rendimiento](#9-consideraciones-de-rendimiento)
10. [Referencias](#10-referencias)

---

## 1. Introducción

### ¿Qué es el BOE?

El **Boletín Oficial del Estado (BOE)** es el diario oficial del Estado español donde se publican:
- Leyes y normativas
- Reales Decretos
- Órdenes ministeriales
- Resoluciones
- Convenios colectivos
- Oposiciones y concursos públicos

### ¿Por qué integrar el BOE en JARVIS?

| Ventaja | Descripción |
|---------|-------------|
| **Información oficial** | Acceso directo a la fuente primaria de legislación española |
| **Actualización en tiempo real** | No requiere mantenimiento de una copia local |
| **Autoridad** | Texto verificado oficialmente, sin riesgo de versiones desactualizadas |
| **Volumen** | El archivo histórico del BOE contiene millones de documentos |

---

## 2. API Open Data del BOE

### Documentación Oficial

- **Portal**: https://www.boe.es/datosabiertos/
- **Descripción**: API RESTful que proporciona acceso programático a las publicaciones del BOE

### Endpoints Disponibles

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/buscar/boe.json` | GET | Búsqueda de texto libre en publicaciones |
| `/diario/boe/{fecha}` | GET | Sumario del día específico |
| `/documento/{id}` | GET | Obtener documento por identificador |
| `/analisis/{id}` | GET | Análisis de normas anteriores/posteriores |
| `/eli/es/{tipo}/{año}/{num}` | GET | Acceso ELI (European Legislation Identifier) |

### Formato de Identifiers

Los documentos del BOE tienen identificadores con el formato:
```
BOE-A-YYYY-NNNNN
```
- `BOE`: Tipo de boletín
- `A`: Sección (A = Disposiciones, B = Autoridades, C = Otras)
- `YYYY`: Año de publicación
- `NNNNN`: Número secuencial

**Ejemplo**: `BOE-A-2018-16673` → Ley Orgánica de Protección de Datos (LOPD)

---

## 3. Arquitectura de Integración

### Diagrama de Flujo

```
┌─────────────────────────────────────────────────────────────────┐
│                    FLUJO DE CONSULTA BOE                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Usuario: "¿Qué dice la Constitución sobre la libertad?"       │
│                          │                                       │
│                          ▼                                       │
│   ┌──────────────────────────────────────┐                      │
│   │   Pipeline (jarvis.py)               │                      │
│   │   _detect_intent() → boe_search      │                      │
│   └──────────────┬───────────────────────┘                      │
│                  │                                               │
│                  ▼                                               │
│   ┌──────────────────────────────────────┐                      │
│   │   BOE Connector (boe_connector.py)   │                      │
│   │   - Parsea keywords                  │                      │
│   │   - Ejecuta búsqueda                 │                      │
│   └──────────────┬───────────────────────┘                      │
│                  │                                               │
│                  ▼                                               │
│   ┌──────────────────────────────────────┐                      │
│   │   API BOE (boe.es/datosabiertos)     │                      │
│   │   Response: JSON con resultados      │                      │
│   └──────────────┬───────────────────────┘                      │
│                  │                                               │
│                  ▼                                               │
│   ┌──────────────────────────────────────┐                      │
│   │   Procesamiento de Resultados        │                      │
│   │   - Extrae títulos y resúmenes       │                      │
│   │   - Obtiene texto completo si aplica │                      │
│   │   - Formatea para contexto LLM       │                      │
│   └──────────────┬───────────────────────┘                      │
│                  │                                               │
│                  ▼                                               │
│   ┌──────────────────────────────────────┐                      │
│   │   LLM (Qwen/LLaMA)                   │                      │
│   │   Sintetiza respuesta con citas      │                      │
│   │   [Fuente: BOE-A-XXXX-XXXXX]         │                      │
│   └──────────────────────────────────────┘                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Componentes

| Componente | Ubicación | Responsabilidad |
|------------|-----------|-----------------|
| Pipeline | `services/openwebui/pipelines/jarvis.py` | Detección de intención y routing |
| BOE Connector | `backend/app/integrations/boe_connector.py` | Comunicación con API BOE |
| Backend | `backend/app/main.py` | Endpoint `/boe/search` |

---

## 4. Implementación Técnica

### Conector BOE

```python
# backend/app/integrations/boe_connector.py

import httpx
from typing import List, Optional
from pydantic import BaseModel

class BOEResult(BaseModel):
    id: str              # BOE-A-2018-16673
    titulo: str          # Título de la disposición
    fecha_publicacion: str
    seccion: str         # Disposiciones, Autoridades, etc.
    departamento: str    # Ministerio emisor
    url_pdf: str         # Enlace al PDF oficial
    texto_resumen: Optional[str] = None

class BOEConnector:
    """
    Conector para la API Open Data del BOE.
    Documentación: https://www.boe.es/datosabiertos/
    """
    
    BASE_URL = "https://www.boe.es/datosabiertos/api"
    TIMEOUT = 15  # segundos
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=self.TIMEOUT)
    
    async def search(
        self, 
        query: str, 
        max_results: int = 5,
        fecha_desde: Optional[str] = None,
        fecha_hasta: Optional[str] = None
    ) -> List[BOEResult]:
        """
        Búsqueda en el BOE por texto libre.
        
        Args:
            query: Términos de búsqueda (ej: "teletrabajo")
            max_results: Número máximo de resultados
            fecha_desde: Filtro fecha inicio (YYYY-MM-DD)
            fecha_hasta: Filtro fecha fin (YYYY-MM-DD)
        
        Returns:
            Lista de BOEResult con los documentos encontrados
        """
        params = {
            "q": query,
            "page_size": max_results,
            "coleccion": "boe",  # Solo BOE, excluir BORME
        }
        
        if fecha_desde:
            params["fecha_publicacion_desde"] = fecha_desde
        if fecha_hasta:
            params["fecha_publicacion_hasta"] = fecha_hasta
        
        response = await self.client.get(
            f"{self.BASE_URL}/buscar/boe.json",
            params=params
        )
        response.raise_for_status()
        
        return self._parse_search_results(response.json())
    
    async def get_document(self, boe_id: str) -> dict:
        """
        Obtiene el texto completo de un documento por su ID.
        
        Args:
            boe_id: Identificador (ej: "BOE-A-2018-16673")
        
        Returns:
            Diccionario con metadatos y texto del documento
        """
        # El ID se usa directamente en la URL
        response = await self.client.get(
            f"{self.BASE_URL}/documento/{boe_id}"
        )
        response.raise_for_status()
        return response.json()
    
    async def get_daily_summary(self, fecha: str) -> List[dict]:
        """
        Obtiene el sumario del BOE para una fecha específica.
        
        Args:
            fecha: Fecha en formato YYYYMMDD
        
        Returns:
            Lista de documentos publicados ese día
        """
        response = await self.client.get(
            f"{self.BASE_URL}/diario/boe/{fecha}"
        )
        response.raise_for_status()
        return response.json().get("data", {}).get("sumario", [])
    
    def _parse_search_results(self, data: dict) -> List[BOEResult]:
        """Parsea la respuesta de búsqueda a objetos BOEResult."""
        results = []
        items = data.get("data", {}).get("items", [])
        
        for item in items:
            results.append(BOEResult(
                id=item.get("identificador", ""),
                titulo=item.get("titulo", "Sin título"),
                fecha_publicacion=item.get("fecha_publicacion", ""),
                seccion=item.get("seccion", ""),
                departamento=item.get("departamento", ""),
                url_pdf=item.get("url_pdf", ""),
                texto_resumen=item.get("texto", "")[:500]  # Limitar resumen
            ))
        
        return results
```

### Endpoint en Backend

```python
# backend/app/main.py (fragmento)

@app.post("/boe/search")
async def search_boe(request: BOESearchRequest):
    """
    Busca en el Boletín Oficial del Estado.
    """
    connector = BOEConnector()
    
    try:
        results = await connector.search(
            query=request.query,
            max_results=request.max_results,
            fecha_desde=request.fecha_desde,
            fecha_hasta=request.fecha_hasta
        )
        
        return {
            "status": "success",
            "query": request.query,
            "results": [r.dict() for r in results],
            "total": len(results)
        }
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=503,
            detail="El servicio del BOE no está disponible. Inténtalo más tarde."
        )
    except Exception as e:
        logger.error(f"Error en búsqueda BOE: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 5. Flujo de Detección de Intención

### Keywords de Activación

El pipeline detecta automáticamente cuándo redirigir al BOE:

```python
# Palabras clave que activan búsqueda BOE
BOE_KEYWORDS = [
    # Referencias directas
    "boe", "boletín oficial", "busca en el boe",
    
    # Tipos de normativa
    "ley orgánica", "real decreto", "orden ministerial",
    "disposición", "resolución", "convenio colectivo",
    
    # Consultas legales comunes
    "legislación sobre", "normativa de", "qué dice la ley",
    "artículo", "publicado oficialmente",
    
    # Siglas comunes
    "lopd", "lopdgdd", "lgt", "et", "lisos"
]

# Patrones regex para detectar consultas específicas
BOE_PATTERNS = [
    r"artículo\s+\d+\s+de\s+la\s+(.+)",      # "artículo 17 de la LOPD"
    r"real\s+decreto\s+\d+/\d+",              # "Real Decreto 123/2024"
    r"ley\s+\d+/\d+",                         # "Ley 14/2013"
    r"BOE-[ABC]-\d{4}-\d+",                   # ID directo "BOE-A-2018-16673"
]
```

### Prioridad de Detección

| Prioridad | Condición | Acción |
|-----------|-----------|--------|
| 1 | Contiene ID de BOE (`BOE-A-...`) | `boe_document` (obtener documento específico) |
| 2 | Matches patrón de ley (`artículo X de Y`) | `boe_search` con extracción de términos |
| 3 | Contiene keywords BOE | `boe_search` con query completa |
| 4 | Default legal keywords | Chat normal (puede sugerir BOE) |

---

## 6. Estrategias de Búsqueda

### Extracción de Keywords

El sistema extrae automáticamente los términos relevantes:

```python
def extract_boe_search_terms(user_message: str) -> str:
    """
    Extrae los términos de búsqueda para el BOE.
    
    Ejemplos:
    - "¿Qué dice la LOPD sobre el derecho al olvido?"
      → "LOPD derecho olvido"
    
    - "Busca en el BOE la normativa de teletrabajo"
      → "normativa teletrabajo"
    """
    # Eliminar frases de activación
    cleaned = re.sub(r'busca en el boe|consulta el boe', '', 
                     user_message, flags=re.IGNORECASE)
    
    # Eliminar stopwords
    stopwords = ['qué', 'dice', 'sobre', 'el', 'la', 'de', 'en', 'que']
    words = cleaned.lower().split()
    filtered = [w for w in words if w not in stopwords and len(w) > 2]
    
    return ' '.join(filtered)
```

### Ejemplos de Transformación

| Input del Usuario | Query al BOE |
|-------------------|--------------|
| "¿Qué dice la LOPD sobre protección de datos?" | "LOPD protección datos" |
| "Busca en el BOE normativa de teletrabajo" | "normativa teletrabajo" |
| "Dame el artículo 17 de la Constitución" | "Constitución artículo 17" |
| "BOE-A-2018-16673" | (llamada directa a get_document) |

---

## 7. Manejo de Errores y Resilencia

### Patrón Circuit Breaker

```python
class BOECircuitBreaker:
    """
    Implementa patrón Circuit Breaker para la API del BOE.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: int = 60
    ):
        self.failures = 0
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.state = "CLOSED"  # CLOSED | OPEN | HALF_OPEN
        self.last_failure_time = None
    
    async def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if self._should_reset():
                self.state = "HALF_OPEN"
            else:
                return self._fallback_response()
        
        try:
            result = await func(*args, **kwargs)
            self._record_success()
            return result
        except Exception as e:
            self._record_failure()
            raise
    
    def _fallback_response(self):
        return {
            "status": "fallback",
            "message": "El servicio del BOE no está disponible actualmente. "
                       "¿Quieres que busque en los documentos locales?",
            "results": []
        }
```

### Timeouts y Retry

| Operación | Timeout | Reintentos | Backoff |
|-----------|---------|------------|---------|
| Búsqueda | 10s | 2 | Exponencial (1s, 2s) |
| Documento | 15s | 1 | - |
| Sumario | 10s | 1 | - |

---

## 8. Ejemplos de Uso

### Ejemplo 1: Consulta General

**Usuario**: "¿Qué dice la ley sobre el teletrabajo?"

**JARVIS**:
```
📜 Legislación sobre Teletrabajo

Según el **Real Decreto-ley 28/2020**, de 22 de septiembre, de trabajo a distancia:

**Definición (Art. 2)**:
El trabajo a distancia es aquella forma de organización del trabajo o de 
realización de la actividad laboral conforme a la cual esta se presta en 
el domicilio de la persona trabajadora o en el lugar elegido por esta, 
durante toda su jornada o parte de ella, con carácter regular.

**Requisitos principales**:
1. Acuerdo individual por escrito
2. Voluntariedad para ambas partes
3. Derecho a la desconexión digital
4. Compensación de gastos

---
📎 **Fuente**: [BOE-A-2020-11043](https://www.boe.es/eli/es/rdl/2020/09/22/28)
📅 **Publicación**: 23 de septiembre de 2020
✅ **Estado**: Vigente
```

### Ejemplo 2: Artículo Específico

**Usuario**: "Dame el artículo 17 de la LOPD"

**JARVIS**:
```
📜 **Artículo 17 - Derecho de supresión** 
(Ley Orgánica 3/2018, de Protección de Datos Personales)

1. El interesado tendrá derecho a obtener sin dilación indebida del 
responsable del tratamiento la supresión de los datos personales que 
le conciernan, el cual estará obligado a suprimir sin dilación los 
datos personales cuando concurra alguna de las circunstancias 
siguientes:

   a) Los datos personales ya no sean necesarios en relación con los 
      fines para los que fueron recogidos.
   
   b) El interesado retire el consentimiento en que se basa el 
      tratamiento.
   
   c) El interesado se oponga al tratamiento con arreglo al artículo 21.
   
   d) Los datos personales hayan sido tratados ilícitamente.

---
📎 **Fuente**: [BOE-A-2018-16673](https://www.boe.es/eli/es/lo/2018/12/05/3/con)
📅 **Publicación**: 6 de diciembre de 2018
```

### Ejemplo 3: Sumario del Día

**Usuario**: "¿Qué se publicó hoy en el BOE?"

**JARVIS**:
```
📰 **Sumario del BOE - 29 de enero de 2026**

📋 **Sección I. Disposiciones generales**
1. Real Decreto 45/2026 - Ministerio de Trabajo
   → Modificación del Estatuto de los Trabajadores

📋 **Sección II. Autoridades y personal**
2. Resolución 28/2026 - Ministerio de Educación
   → Convocatoria de becas FPU 2026

📋 **Sección III. Otras disposiciones**
3. Orden TMA/89/2026 - Ministerio de Transportes
   → Actualización de tarifas de peajes

---
🔗 Ver sumario completo: https://www.boe.es/boe/dias/2026/01/29/
```

---

## 9. Consideraciones de Rendimiento

### Estrategia de Caché

| Tipo de Consulta | TTL | Justificación |
|------------------|-----|---------------|
| Sumario del día | 1 hora | Actualización diaria del BOE |
| Documento específico | Permanente | Los documentos publicados son inmutables |
| Búsqueda libre | Sin caché | Resultados pueden variar por relevancia |

### Métricas Prometheus

```python
# Métricas de monitorización
boe_requests_total = Counter(
    'boe_requests_total',
    'Total de peticiones al BOE',
    ['endpoint', 'status']
)

boe_latency_seconds = Histogram(
    'boe_latency_seconds',
    'Latencia de peticiones al BOE',
    ['endpoint']
)
```

---

## 10. Referencias

### Documentación Oficial
- [API Open Data BOE](https://www.boe.es/datosabiertos/)
- [Guía de uso de la API](https://www.boe.es/datosabiertos/documentacion/api/)
- [European Legislation Identifier (ELI)](https://eur-lex.europa.eu/eli-register/about.html)

### Legislación Relevante
- [Ley 19/2013](https://www.boe.es/eli/es/l/2013/12/09/19/con) - Transparencia y acceso a información pública
- [Real Decreto 181/2008](https://www.boe.es/eli/es/rd/2008/02/08/181) - Ordenación del BOE

---

*Documento generado para el TFG - Universidad Rey Juan Carlos*

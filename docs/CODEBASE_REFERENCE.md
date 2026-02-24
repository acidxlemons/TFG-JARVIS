# 📜 Codebase Reference: Mapa de Código - JARVIS

**Proyecto**: TFG - Universidad Rey Juan Carlos

> **Objetivo**: Documento técnico que describe la función y responsabilidad de cada script y módulo en el repositorio.

---

## 📁 Estructura General del Proyecto

```
TFG-RAG-Clean/
├── backend/               # API principal (FastAPI)
├── services/              # Microservicios (Indexer, OpenWebUI, LiteLLM)
├── mcp-boe-server/        # Servidor MCP para el BOE
├── scripts/               # Utilidades y scripts de mantenimiento
├── config/                # Configuración de servicios
├── docs/                  # Documentación
├── docker-compose.yml     # Orquestación de contenedores
└── .env                   # Variables de entorno
```

---

## 🏛️ 1. MCP BOE Server (`/mcp-boe-server`)

Servidor que expone la API del Boletín Oficial del Estado mediante el protocolo MCP.

| Archivo | Descripción | Líneas |
|---------|-------------|--------|
| **`mcp_boe_server.py`** | **Servidor principal**. Define las 7 herramientas MCP (`get_boe_summary`, `search_legislation`, etc.) usando FastMCP. Soporta modo STDIO y HTTP. | ~200 |
| **`boe_connector.py`** | **Conector API**. Toda la lógica de llamadas HTTP a la API Open Data del BOE. Métodos para sumario, búsqueda, consolidados, análisis. | ~400 |
| **`test_mcp_real.py`** | **Test completo**. Conecta al servidor MCP, lista herramientas, ejecuta llamadas reales y verifica respuestas. | ~150 |
| **`test_mcp_direct.py`** | Test HTTP directo al endpoint `/mcp`. | ~100 |
| **`test_mcp_boe.py`** | Test básico de conexión. | ~50 |
| **`requirements.txt`** | Dependencias: `fastmcp`, `requests`. | 2 |
| **`Dockerfile`** | Imagen Docker para despliegue containerizado. | ~20 |
| **`claude_desktop_config.json`** | Ejemplo de configuración para Claude Desktop. | ~10 |

---

## 🖥️ 2. Backend Principal (`/backend/app`)

El "cerebro" del sistema. API REST con FastAPI.

### 2.1 Archivo Principal

| Archivo | Descripción |
|---------|-------------|
| **`main.py`** | **Entrada de la API**. Define todos los endpoints REST. Incluye: `/api/v1/search`, `/api/v1/chat`, `/scrape/url`, `/documents/list`, `/boe/*`. Es el archivo más grande (~2000 líneas). |

### 2.2 Carpeta `/api` - Endpoints

| Archivo | Descripción |
|---------|-------------|
| **`chat.py`** | Endpoint `/chat`. Flujo conversacional principal. Detecta intención (RAG vs charla), gestiona historial. |
| **`documents.py`** | Endpoints para subir documentos (`POST /documents/upload`) y listar (`GET /documents/list`). |
| **`web_search.py`** | Endpoint de búsqueda web. Usa DuckDuckGo (con fallback a HTML scraping). |
| **`scrape.py`** | Endpoint `/scrape/url`. Scrapea URLs, extrae texto, lo indexa en Qdrant (colección `webs`). |

### 2.3 Carpeta `/core` - Lógica Central

| Archivo | Descripción |
|---------|-------------|
| **`rag/retriever.py`** | **Motor RAG**. Consulta Qdrant con búsqueda híbrida (semántica + léxica), aplica filtros, hace Reranking. |
| **`rag/chain.py`** | **Orquestador**. Combina documentos recuperados, construye prompt, llama al LLM. |
| **`agent/tools.py`** | Define herramientas (Tools) que el agente puede usar. |
| **`memory/manager.py`** | Gestiona memoria conversacional (historial) en Redis/Postgres. |
| **`query_processor.py`** | Limpia queries: quita saludos, reformula para mejor búsqueda. |

### 2.4 Carpeta `/processing` - Procesamiento de Documentos

| Archivo | Descripción |
|---------|-------------|
| **`ocr/paddle_ocr.py`** | Motor OCR con GPU. Usa PaddlePaddle para convertir PDFs escaneados a texto. |
| **`chunking/smart_chunker.py`** | Divide textos largos en fragmentos lógicos respetando párrafos. |
| **`embeddings/sentence_transformer.py`** | Genera vectores (embeddings) usando Sentence Transformers. |

### 2.5 Carpeta `/integrations` - Conectores Externos

| Archivo | Descripción |
|---------|-------------|
| **`boe_connector.py`** | Conector al BOE (usado por el backend directamente, distinto al MCP). |
| **`sharepoint/client.py`** | Cliente Microsoft Graph para SharePoint. |
| **`sharepoint/sync.py`** | Sincronización delta (solo cambios) con SharePoint. |
| **`scraper/playwright_scraper.py`** | Navegador headless para webs dinámicas (JavaScript). |

### 2.6 Carpeta `/storage`

| Archivo | Descripción |
|---------|-------------|
| **`qdrant_client.py`** | Wrapper para operaciones en Qdrant (upsert, search, delete). |
| **`postgres_client.py`** | Conexión a PostgreSQL para metadatos. |
| **`redis_client.py`** | Cliente Redis para cache. |

---

## 🔌 3. Pipeline OpenWebUI (`/services/openwebui/pipelines`)

### 3.1 jarvis.py (Pipeline Principal)

El "Director de Orquesta" que decide qué hacer con cada mensaje.

| Función | Propósito |
|---------|-----------|
| **`pipe()`** | Punto de entrada. Recibe mensaje, decide acción, retorna respuesta. |
| **`_detect_intent()`** | Determina intención: `rag`, `chat`, `web_search`, `boe`, `ocr`, `url`. |
| **`_is_boe_query()`** | Detecta si el mensaje pide información del BOE. |
| **`_detect_url_in_query()`** | Extrae URLs del mensaje con regex. |
| **`_wants_web_search()`** | Detecta "busca en internet", "busca en la web", etc. |
| **`_wants_rag_search()`** | Detecta "busca en tus documentos", "consulta los archivos". |
| **`_call_backend_chat()`** | Llama a `/chat` del backend con contexto RAG. |
| **`_call_boe_search()`** | Llama al endpoint BOE del backend. |
| **`_call_litellm_with_history()`** | Llama al LLM con historial conversacional. |
| **`_build_chat_history()`** | Extrae historial de OpenWebUI. |

---

## 🔄 4. Indexer Service (`/services/indexer`)

Servicio independiente que mantiene Qdrant actualizado.

| Archivo | Descripción |
|---------|-------------|
| **`main.py`** | API de control: `/scan`, `/sync`, `/status`. |
| **`worker.py`** | **Obrero principal**. Loop que vigila `data/watch`, detecta archivos nuevos, ejecuta OCR+Chunking+Indexación. |
| **`multi_site_sync.py`** | Gestor de múltiples sitios SharePoint. Lee `sharepoint_sites.json`, lanza sincronizaciones paralelas. |
| **`ocr_processor.py`** | Delegador de OCR (local o servicio remoto). |

---

## ⚙️ 5. Scripts de Operaciones (`/scripts`)

### 5.1 Fine-Tuning & Entrenamiento

| Archivo | Descripción |
|---------|-------------|
| **`finetune_embeddings_v2.py`** | Fine-tuning de embeddings con Multiple Negatives Ranking Loss. |
| **`generate_dataset_from_qdrant.py`** | Genera pares Pregunta-Respuesta sintéticos desde Qdrant. |
| **`evaluate_rag.py`** | Evalúa precisión del RAG contra Gold Dataset. |
| **`finetune_reranker.py`** | Entrena el Cross-Encoder (Reranker). |
| **`finetune_lora.py`** | Entrena adaptadores LoRA para el LLM. |
| **`convert_lora_to_ollama.py`** | Convierte LoRA a GGUF para Ollama. |

### 5.2 Gestión y Utilidades

| Archivo | Descripción |
|---------|-------------|
| **`add_sharepoint_site.py`** | Asistente CLI para añadir sitios SharePoint. |
| **`setup.sh`** | Instalador: Docker, NVIDIA drivers, carpetas. |
| **`backup.sh`** / **`restore.sh`** | Backups de Qdrant y PostgreSQL. |
| **`pull_models.sh`** | Descarga modelos de Ollama. |

---

## 🔧 6. Configuración (`/config`)

| Carpeta/Archivo | Descripción |
|-----------------|-------------|
| **`nginx/nginx.conf`** | Configuración del reverse proxy. |
| **`nginx/ssl/`** | Certificados SSL. |
| **`prometheus/prometheus.yml`** | Scrape targets para métricas. |
| **`grafana/provisioning/`** | Datasources y dashboards pre-configurados. |
| **`grafana/dashboards/enterprise_rag.json`** | Dashboard personalizado del sistema. |

---

## 🐳 7. Docker Compose (`docker-compose.yml`)

Define los 14 microservicios:

| Servicio | Puerto | Descripción |
|----------|--------|-------------|
| `nginx` | 8443, 80 | Reverse proxy + SSL |
| `openwebui` | 3002 | Interfaz de chat |
| `tfg-backend` | 8002 | API principal |
| `mcp-boe` | 8011 | Servidor MCP |
| `qdrant` | 6335 | Base de datos vectorial |
| `postgres` | 5433 | Metadatos y usuarios |
| `redis` | 6380 | Cache |
| `litellm` | 4001 | Proxy de LLMs |
| `ollama` | 11435 | Servidor de modelos |
| `indexer` | 8003 | Sincronización |
| `prometheus` | 9091 | Métricas |
| `grafana` | 3003 | Dashboards |
| `minio` | 9002 | Almacenamiento S3 |
| `dcgm-exporter` | 9401 | Métricas GPU |

---

## 🧪 8. Tests (`/tests` y archivos raíz)

| Archivo | Descripción |
|---------|-------------|
| **`test_boe_connection.py`** | Verifica conexión al BOE. |
| **`test_boe_search.py`** | Prueba búsquedas en el BOE. |
| **`test_boe_law_text.py`** | Prueba obtención de texto de leyes. |
| **`test_boe_analysis.py`** | Prueba análisis jurídico. |
| **`check_boe_sections.py`** | Verifica secciones del BOE. |

---

## 📚 9. Documentación (`/docs`)

| Archivo | Propósito |
|---------|-----------|
| **`README.md`** | Índice de documentación |
| **`TECHNOLOGY_STACK.md`** | Explicación de tecnologías |
| **`ENV_CONFIGURATION.md`** | Variables de entorno |
| **`DEPLOYMENT_CHECKLIST.md`** | Guía de despliegue |
| **`TECHNICAL_ARCHITECTURE.md`** | Arquitectura detallada |
| **`STUDENT_GUIDE.md`** | Guía para TFG |
| **`USER_GUIDE.md`** | Manual de usuario |
| **`SHAREPOINT_INTEGRATION.md`** | Integración SharePoint |
| **`ADVANCED_EXTENSIONS.md`** | MCP, SSO, Nginx |
| **`BOE_INTEGRATION.md`** | Integración BOE |
| **`FINE_TUNING_GUIDE.md`** | Fine-tuning |

---

*Última actualización: Febrero 2026*  
*Universidad Rey Juan Carlos - TFG*

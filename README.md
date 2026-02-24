<p align="center">
  <img src="docs/assets/urjc-logo.png" alt="JARVIS - URJC" width="200">
</p>

<h1 align="center">🤖 JARVIS - Intelligent RAG Assistant</h1>

<p align="center">
  <strong>Trabajo de Fin de Grado - Universidad Rey Juan Carlos</strong><br>
  Sistema de IA conversacional con RAG, búsqueda web, OCR y conexión al BOE.
</p>

<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick%20Start-5%20min-brightgreen?style=for-the-badge" alt="Quick Start"></a>
  <a href="#-características"><img src="https://img.shields.io/badge/Features-20+-blue?style=for-the-badge" alt="Features"></a>
  <a href="docs/FINE_TUNING_GUIDE.md"><img src="https://img.shields.io/badge/Fine--Tuning-Guide-orange?style=for-the-badge" alt="Fine-Tuning"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776ab?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Docker-Compose-2496ed?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76b900?logo=nvidia&logoColor=white" alt="NVIDIA">
  <img src="https://img.shields.io/badge/LLM-Ollama%20%2B%20LiteLLM-black?logo=meta&logoColor=white" alt="LLM">
  <img src="https://img.shields.io/badge/Vectors-Qdrant-dc382d?logo=redis&logoColor=white" alt="Qdrant">
</p>

---

## 📖 Tabla de Contenidos

- [🎯 ¿Qué es esto?](#-qué-es-esto)
- [✨ Características](#-características)
- [🏗️ Arquitectura](#️-arquitectura)
- [🚀 Quick Start](#-quick-start)
- [⚙️ Configuración](#️-configuración)
- [📊 Monitoreo](#-monitoreo)
- [🎓 Fine-Tuning](#-fine-tuning)
- [🔐 Seguridad](#-seguridad)
- [📚 Documentación](#-documentación)
- [🤝 Contribuir](#-contribuir)
- [📄 Licencia](#-licencia)

---

## 🎯 ¿Qué es esto?

**JARVIS** es un asistente de IA inteligente desarrollado como TFG en la URJC que permite:
- Consultar documentos mediante lenguaje natural (RAG)
- Buscar información en internet
- Analizar páginas web y PDFs
- Consultar el **Boletín Oficial del Estado (BOE)** en tiempo real
- Procesar imágenes con OCR

### El Problema que Resuelve

| ❌ Antes | ✅ Después |
|----------|-----------|
| "¿Dónde está ese documento?" | "¿Qué dice la normativa sobre X?" |
| Buscar en múltiples fuentes | Respuesta unificada con **fuentes citadas** |
| Consultar BOE manualmente | "¿Qué modifica la LOPD?" → Respuesta inmediata |

### ¿Por qué Local y No ChatGPT/Copilot?

```
┌─────────────────────────────────────────────────────────────────┐
│  🔒 SOBERANÍA DE DATOS                                          │
│                                                                   │
│  • Documentos NUNCA salen de tu infraestructura                 │
│  • Cumplimiento GDPR/RGPD por diseño                            │
│  • Sin dependencia de APIs externas ni costes por token         │
│  • Control total sobre el modelo y sus respuestas               │
└─────────────────────────────────────────────────────────────────┘
```

---

## ✨ Características

### 🧠 Core RAG
- **🔍 Búsqueda Híbrida** — Semántica (embeddings) + Léxica (keywords) + Reranking
- **📚 Citaciones Automáticas** — Referencias `[1], [2], [3]` con archivo y página
- **🎯 Detección de Intención** — Adapta la estrategia según el tipo de pregunta
- **🌐 Multi-idioma** — Detecta y responde en tu idioma

### 🏛️ Conectores Externos
- **📰 BOE API** — Consulta legislación, sumarios, texto de leyes
- **🔗 Web Scraping** — Analiza URLs en tiempo real
- **🌐 Web Search** — Búsqueda en internet con SearXNG

### 📄 Procesamiento de Documentos
- **📑 OCR Inteligente** — PaddleOCR con GPU para PDFs escaneados
- **📊 Multi-formato** — PDF, DOCX, TXT, XLSX
- **✂️ Chunking Semántico** — Fragmentación preservando contexto

### 📊 Observabilidad
- **📈 Prometheus + Grafana** — Métricas de latencia, uso, GPU
- **🔍 GPU Monitoring** — NVIDIA DCGM Exporter

> **Nota:** Este sistema también soporta SSO con Azure AD y sincronización con SharePoint, pero estas funcionalidades requieren configuración adicional y credenciales corporativas.

---

## 🏗️ Arquitectura

```
┌──────────────────────────────────────────────────────────────────────┐
│                              USUARIO                                   │
│                         (Browser / API)                                │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ HTTPS (8443)
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         🔒 NGINX (SSL)                                 │
│                      Reverse Proxy + WAF                               │
└─────────────────────────────┬────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│      🖥️ OpenWebUI        │     │     📡 RAG Backend       │
│    (Chat Interface)      │────▶│      (FastAPI)           │
│   + Pipeline Agent       │     │  • Hybrid Search         │
│   + SSO Azure AD         │     │  • Query Processor       │
└─────────────────────────┘     │  • OCR Pipeline          │
                                └───────────┬─────────────┘
                                            │
     ┌──────────────────┬───────────────────┼───────────────────┐
     ▼                  ▼                   ▼                   ▼
┌──────────┐     ┌──────────┐       ┌──────────────┐     ┌──────────┐
│  🧮 Qdrant │     │ 🐘 Postgres│      │ 🤖 LiteLLM    │     │ 💾 Redis  │
│ (Vectors) │     │ (Metadata)│      │   ↓ Ollama    │     │ (Cache)  │
│  HNSW     │     │  Users    │      │  LLaMA 3.1   │     │  TTL 1h  │
└──────────┘     └──────────┘       └──────────────┘     └──────────┘
     │
     │ Sync cada 5min
     ▼
┌──────────────────────────┐
│   📤 SharePoint Indexer   │
│  • Microsoft Graph API   │
│  • Delta Token Sync      │
│  • Multi-Site Support    │
└──────────────────────────┘
```

**14 Microservicios** orquestados con Docker Compose:

| Servicio | Puerto | Función |
|----------|--------|---------|
| `nginx` | 8443, 80 | Reverse proxy + SSL |
| `openwebui` | 3002 | Interfaz de chat |
| `tfg-backend` | 8002 | API de búsqueda y procesamiento |
| `mcp-boe` | 8011 | **MCP Server** - Consultas BOE |
| `qdrant` | 6335 | Base de datos vectorial |
| `postgres` | 5433 | Metadatos y usuarios |
| `redis` | 6380 | Cache de respuestas |
| `litellm` | 4001 | Proxy de LLMs |
| `ollama` | 11435 | Servidor de modelos locales |
| `indexer` | 8003 | Sincronización SharePoint |
| `prometheus` | 9091 | Recolección de métricas |
| `grafana` | 3003 | Dashboards |
| `minio` | 9002 | Almacenamiento S3 |
| `dcgm-exporter` | 9401 | Métricas GPU |

### 🏛️ MCP Server BOE

El sistema incluye un **servidor MCP** (Model Context Protocol) para consultar el Boletín Oficial del Estado:

```bash
# Verificar que funciona
cd mcp-boe-server
python test_mcp_real.py

# Resultado:
# [SUCCESS] MCP SERVER FUNCIONA CORRECTAMENTE!
# Herramientas: 7
```

**Herramientas disponibles:**

| Herramienta | Descripción |
|-------------|-------------|
| `get_boe_summary` | Sumario del BOE de hoy |
| `search_legislation` | Buscar leyes por texto |
| `get_law_text` | Texto completo de una ley |
| `get_law_analysis` | Análisis jurídico |
| `resolve_law_name` | Resolver LOPD → BOE-A-2018-16673 |

**Clientes compatibles:** Claude Desktop, Continue.dev, Cline (VS Code), scripts Python.

📖 Ver [Documentación MCP](mcp-boe-server/README.md)

---

## 🚀 Quick Start

### Prerrequisitos

| Requisito | Mínimo | Recomendado |
|-----------|--------|-------------|
| **RAM** | 16 GB | 32+ GB |
| **CPU** | 4 cores | 8+ cores |
| **GPU** | - | NVIDIA 8+ GB VRAM |
| **Disco** | 50 GB SSD | 200+ GB NVMe |
| **Docker** | v24+ | Latest |
| **Docker Compose** | v2.20+ | Latest |

### Instalación (5 minutos)

```bash
# 1. Clonar repositorio
git clone https://github.com/acidxlemons/TFG-JARVIS.git
cd TFG-JARVIS

# 2. Configurar variables de entorno
cp .env.example .env
# ⚠️ IMPORTANTE: Editar .env con tus credenciales
nano .env  # o tu editor preferido

# 3. Iniciar todos los servicios
docker compose up -d

# 4. Verificar que todo está corriendo
docker compose ps

# 5. Descargar modelo LLM (primera vez)
docker compose exec ollama ollama pull llama3.1:8b-instruct-q8_0
```

### Verificar Instalación

```bash
# Health check general
curl http://localhost:8002/health

# Verificar Qdrant
curl http://localhost:6335/health

# Acceder a la interfaz
open http://localhost:3002   # macOS
start http://localhost:3002  # Windows
xdg-open http://localhost:3002  # Linux
```

### Tu Primera Consulta

1. Abre `http://localhost:3002`
2. Selecciona el pipeline "JARVIS"
3. Prueba estas consultas:
   - *"¿Qué dice el BOE de hoy?"*
   - *"Dame el artículo 5 de la LOPD"*
   - *"Analiza esta URL: https://..."*

---

## ⚙️ Configuración

### Variables de Entorno Esenciales

```bash
# ========================================
# MÍNIMO REQUERIDO
# ========================================

# Contraseñas (CAMBIAR OBLIGATORIAMENTE)
POSTGRES_PASSWORD=CHANGE_THIS_PASSWORD
GRAFANA_PASSWORD=CHANGE_THIS_PASSWORD

# ========================================
# OPCIONAL - Azure AD / SharePoint
# (Solo si deseas SSO corporativo)
# ========================================

# AZURE_TENANT_ID=your-tenant-id
# AZURE_CLIENT_ID=your-client-id  
# AZURE_CLIENT_SECRET=your-client-secret
```

### Configuración SharePoint (Opcional)

Si deseas sincronizar documentos desde SharePoint:

1. **Crear `config/sharepoint_sites.json`:**

```json
{
  "sites": [
    {
      "name": "MiSitio",
      "site_id": "tu-site-id-aqui",
      "folder_path": "Documents/RAG",
      "collection_name": "documents_MiSitio",
      "enabled": true
    }
  ]
}
```

2. **Obtener Site ID** desde [Microsoft Graph Explorer](https://developer.microsoft.com/graph/graph-explorer)

3. **Configurar permisos** en Azure Portal → App Registration → API Permissions:
   - `Sites.Read.All`
   - `Files.Read.All`

---

## 📊 Monitoreo

### Acceso a Dashboards

| Dashboard | URL | Credenciales |
|-----------|-----|--------------|
| **Grafana** | http://localhost:3003 | admin / (ver `.env`) |
| **Prometheus** | http://localhost:9091 | - |
| **Métricas Backend** | http://localhost:8002/metrics | - |

### Métricas Clave

```promql
# Latencia p95 de búsquedas
histogram_quantile(0.95, rate(rag_search_duration_seconds_bucket[5m]))

# Hit rate (búsquedas exitosas)
rate(rag_search_hits_total[5m]) / rate(rag_search_requests_total[5m])

# Uso de GPU
DCGM_FI_DEV_GPU_UTIL
```

---

## 🎓 Fine-Tuning

Este sistema soporta fine-tuning de 3 componentes:

| Componente | Técnica | Cuándo usarlo |
|------------|---------|---------------|
| **LLM** | LoRA | Cambiar formato de respuestas, tono |
| **Embeddings** | Full FT | Vocabulario corporativo específico |
| **Reranker** | Contrastive | Mejorar precisión de ranking |

📖 **[Ver Guía Completa de Fine-Tuning](docs/FINE_TUNING_GUIDE.md)**

### Quick Fine-Tuning (Embeddings)

```bash
# 1. Generar dataset desde documentos indexados
python scripts/generate_dataset_from_qdrant.py --output data/dataset.json

# 2. Entrenar embeddings
python scripts/finetune_embeddings.py --dataset data/dataset.json --epochs 3

# 3. Re-indexar con nuevo modelo
python scripts/reindex_with_finetuned.py
```

---

## 🔐 Seguridad

### Modelo de Seguridad

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FLUJO DE AUTORIZACIÓN                             │
├─────────────────────────────────────────────────────────────────────┤
│  1. Usuario → Azure AD SSO → OpenWebUI (obtiene JWT)                │
│  2. JWT contiene grupos del usuario                                  │
│  3. Pipeline mapea grupos → colecciones Qdrant                      │
│  4. Búsqueda RAG filtra SOLO colecciones autorizadas               │
└─────────────────────────────────────────────────────────────────────┘
```

### Checklist de Seguridad

- [ ] Cambiar TODAS las contraseñas en `.env`
- [ ] Configurar certificados SSL válidos (no autofirmados en producción)
- [ ] Habilitar firewall para puertos internos
- [ ] Configurar Azure AD con MFA
- [ ] Revisar permisos de archivos (`chmod 600 .env`)

---

## 📚 Documentación

Toda la documentación está en la carpeta [`docs/`](docs/README.md).

### 🚀 Empezando
| Documento | Descripción |
|-----------|-------------|
| 📖 **[DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md)** | Guía paso a paso de despliegue |
| ⚙️ **[ENV_CONFIGURATION.md](docs/ENV_CONFIGURATION.md)** | Configuración de variables de entorno |
| 🛠️ **[TECHNOLOGY_STACK.md](docs/TECHNOLOGY_STACK.md)** | Explicación de cada tecnología |

### 📘 Guías Técnicas
| Documento | Descripción |
|-----------|-------------|
| 🏗️ **[TECHNICAL_ARCHITECTURE.md](docs/TECHNICAL_ARCHITECTURE.md)** | Arquitectura completa del sistema |
| 📜 **[CODEBASE_REFERENCE.md](docs/CODEBASE_REFERENCE.md)** | Mapa de todos los archivos de código |
| 🎓 **[STUDENT_GUIDE.md](docs/STUDENT_GUIDE.md)** | Guía para defensa académica (TFG) |
| 🧠 **[FINE_TUNING_GUIDE.md](docs/FINE_TUNING_GUIDE.md)** | Cómo entrenar modelos personalizados |

### 🔌 Integraciones
| Documento | Descripción |
|-----------|-------------|
| 🏛️ **[BOE_INTEGRATION.md](docs/BOE_INTEGRATION.md)** | Integración con el Boletín Oficial del Estado |
| 🤖 **[mcp-boe-server/README.md](mcp-boe-server/README.md)** | Servidor MCP para el BOE |
| 🔗 **[ADVANCED_EXTENSIONS.md](docs/ADVANCED_EXTENSIONS.md)** | MCP, SSO, Nginx avanzado |
| ☁️ **[SHAREPOINT_INTEGRATION.md](docs/SHAREPOINT_INTEGRATION.md)** | Sincronización con SharePoint |

### 👤 Usuario Final
| Documento | Descripción |
|-----------|-------------|
| 📗 **[USER_GUIDE.md](docs/USER_GUIDE.md)** | Manual de usuario |
| 🧪 **[TESTING_GUIDE.md](docs/TESTING_GUIDE.md)** | Guía de testing |

---

## 🛠️ Troubleshooting

### Problemas Comunes

<details>
<summary><strong>❌ "No encuentra documentos"</strong></summary>

```bash
# 1. Verificar que hay documentos indexados
curl http://localhost:6335/collections/documents

# 2. Verificar tenant_id correcto
# El tenant del usuario debe coincidir con el de los documentos

# 3. Bajar umbral de confianza
# En el pipeline, ajustar MIN_CONFIDENCE a 0.3
```
</details>

<details>
<summary><strong>❌ "Latencia muy alta (>5s)"</strong></summary>

```bash
# 1. Verificar GPU
nvidia-smi

# 2. Deshabilitar reranking temporalmente
# En .env: ENABLE_RERANKING=false

# 3. Verificar recursos
docker stats
```
</details>

<details>
<summary><strong>❌ "Error de conexión al backend"</strong></summary>

```bash
# 1. Verificar que backend está corriendo
docker compose ps tfg-backend

# 2. Ver logs
docker compose logs tfg-backend --tail=50

# 3. Reiniciar servicios
docker compose restart tfg-backend
```
</details>

---

## 🤝 Contribuir

¡Las contribuciones son bienvenidas! 

### Cómo Contribuir

1. **Fork** el repositorio
2. **Crea** una rama (`git checkout -b feature/AmazingFeature`)
3. **Commit** tus cambios (`git commit -m 'Add AmazingFeature'`)
4. **Push** a la rama (`git push origin feature/AmazingFeature`)
5. **Abre** un Pull Request

### Código de Conducta

Este proyecto sigue el [Contributor Covenant](https://www.contributor-covenant.org/).

---

## 📄 Licencia

Este proyecto está bajo la licencia **MIT**. Ver [LICENSE](LICENSE) para más detalles.

---

## 🌟 Créditos y Tecnologías

| Tecnología | Uso |
|------------|-----|
| [Qdrant](https://qdrant.tech/) | Base de datos vectorial |
| [Ollama](https://ollama.ai/) | Servidor de LLMs locales |
| [OpenWebUI](https://github.com/open-webui/open-webui) | Interfaz de chat |
| [LiteLLM](https://github.com/BerriAI/litellm) | Proxy de LLMs |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | OCR open source |
| [BOE API](https://boe.es/datosabiertos/) | Datos abiertos del BOE |

---

<p align="center">
  <strong>JARVIS - Trabajo de Fin de Grado</strong><br>
  <em>Universidad Rey Juan Carlos - 2026</em>
</p>

<p align="center">
  <a href="#-jarvis---intelligent-rag-assistant">⬆️ Volver arriba</a>
</p>

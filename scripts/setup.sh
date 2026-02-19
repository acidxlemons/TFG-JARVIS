#!/bin/bash
# scripts/setup.sh

# ============================================
# SCRIPT DE SETUP INICIAL
# Sistema RAG Empresarial
# ============================================

set -e  # Exit on error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "============================================"
echo "  SETUP - Sistema RAG Empresarial"
echo "============================================"
echo -e "${NC}"

# ============================================
# VERIFICAR REQUISITOS
# ============================================

check_requirements() {
    echo -e "${YELLOW}Verificando requisitos...${NC}"
    
    # Docker
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker no encontrado. Instala Docker primero.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Docker instalado${NC}"
    
    # Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        echo -e "${RED}❌ Docker Compose no encontrado.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Docker Compose instalado${NC}"
    
    # NVIDIA GPU (opcional pero recomendado)
    if command -v nvidia-smi &> /dev/null; then
        echo -e "${GREEN}✓ NVIDIA GPU detectada${NC}"
        nvidia-smi --query-gpu=name --format=csv,noheader
        HAS_GPU=true
    else
        echo -e "${YELLOW}⚠ GPU NVIDIA no detectada. El sistema funcionará sin aceleración GPU.${NC}"
        HAS_GPU=false
    fi
    
    echo ""
}

# ============================================
# CONFIGURAR VARIABLES DE ENTORNO
# ============================================

setup_env() {
    echo -e "${YELLOW}Configurando variables de entorno...${NC}"
    
    if [ -f .env ]; then
        echo -e "${YELLOW}⚠ Archivo .env ya existe. ¿Sobrescribir? (y/N)${NC}"
        read -r response
        if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
            echo "Usando .env existente"
            return
        fi
    fi
    
    # Copiar template
    cp .env.example .env
    
    # Generar passwords aleatorios
    POSTGRES_PASS=$(openssl rand -base64 32)
    MINIO_PASS=$(openssl rand -base64 32)
    LITELLM_KEY="sk-$(openssl rand -hex 16)"
    WEBHOOK_SECRET=$(openssl rand -hex 32)
    JWT_SECRET=$(openssl rand -hex 32)
    
    # Actualizar .env
    sed -i "s/POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${POSTGRES_PASS}/" .env
    sed -i "s/MINIO_ROOT_PASSWORD=.*/MINIO_ROOT_PASSWORD=${MINIO_PASS}/" .env
    sed -i "s/LITELLM_MASTER_KEY=.*/LITELLM_MASTER_KEY=${LITELLM_KEY}/" .env
    sed -i "s/WEBHOOK_SECRET=.*/WEBHOOK_SECRET=${WEBHOOK_SECRET}/" .env
    sed -i "s/JWT_SECRET=.*/JWT_SECRET=${JWT_SECRET}/" .env
    
    echo -e "${GREEN}✓ Variables de entorno configuradas${NC}"
    echo -e "${YELLOW}⚠ IMPORTANTE: Edita .env y completa:${NC}"
    echo "  - AZURE_TENANT_ID"
    echo "  - AZURE_CLIENT_ID"
    echo "  - AZURE_CLIENT_SECRET"
    echo "  - SHAREPOINT_SITE_ID (si usas SharePoint)"
    echo ""
    
    echo -e "${YELLOW}Presiona ENTER para continuar una vez completado...${NC}"
    read
}

# ============================================
# CREAR DIRECTORIOS
# ============================================

create_directories() {
    echo -e "${YELLOW}Creando estructura de directorios...${NC}"
    
    mkdir -p data/sharepoint
    mkdir -p data/uploads
    mkdir -p data/processed
    mkdir -p backend/app/cache/ocr
    mkdir -p logs
    
    echo -e "${GREEN}✓ Directorios creados${NC}"
    echo ""
}

# ============================================
# INICIAR INFRAESTRUCTURA BASE
# ============================================

start_infrastructure() {
    echo -e "${YELLOW}Iniciando servicios de infraestructura...${NC}"
    
    # Bases de datos primero
    docker-compose up -d postgres redis qdrant minio
    
    echo "Esperando a que los servicios estén listos..."
    sleep 15
    
    # Verificar salud
    echo "Verificando servicios..."
    docker-compose ps
    
    echo -e "${GREEN}✓ Infraestructura iniciada${NC}"
    echo ""
}

# ============================================
# INICIALIZAR BASE DE DATOS
# ============================================

init_database() {
    echo -e "${YELLOW}Inicializando base de datos...${NC}"
    
    # Esperar a que Postgres esté listo
    until docker-compose exec -T postgres pg_isready -U rag_user; do
        echo "Esperando Postgres..."
        sleep 2
    done
    
    # Crear tablas iniciales
    docker-compose exec -T postgres psql -U rag_user -d rag_system << 'EOF'
-- Tabla de usuarios
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    azure_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla de conversaciones
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_archived BOOLEAN DEFAULT FALSE,
    summary TEXT,
    summary_generated_at TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- Tabla de mensajes
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    sources_used JSONB,
    retrieval_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_users_azure_id ON users(azure_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

EOF
    
    echo -e "${GREEN}✓ Base de datos inicializada${NC}"
    echo ""
}

# ============================================
# INICIALIZAR QDRANT
# ============================================

init_qdrant() {
    echo -e "${YELLOW}Inicializando Qdrant...${NC}"
    
    # Esperar a que Qdrant esté listo
    until curl -f http://localhost:6333/health &>/dev/null; do
        echo "Esperando Qdrant..."
        sleep 2
    done
    
    # Crear colección
    curl -X PUT http://localhost:6333/collections/documentos \
      -H 'Content-Type: application/json' \
      -d '{
        "vectors": {
          "size": 384,
          "distance": "Cosine"
        },
        "optimizers_config": {
          "indexing_threshold": 10000
        }
      }' &>/dev/null
    
    echo -e "${GREEN}✓ Colección 'documentos' creada en Qdrant${NC}"
    echo ""
}

# ============================================
# DESCARGAR MODELOS OLLAMA
# ============================================

download_models() {
    echo -e "${YELLOW}Descargando modelos LLM (esto puede tomar 10-20 minutos)...${NC}"
    
    # Iniciar Ollama
    docker-compose up -d ollama
    sleep 10
    
    # Modelo principal
    echo "Descargando llama3.1:8b-instruct-q8_0..."
    docker-compose exec -T ollama ollama pull llama3.1:8b-instruct-q8_0
    
    # Modelo de visión (opcional)
    echo -e "${YELLOW}¿Descargar modelo de visión llava:13b? (y/N)${NC}"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        docker-compose exec -T ollama ollama pull llava:13b
    fi
    
    # Modelo ligero para resúmenes
    echo "Descargando modelo ligero para resúmenes..."
    docker-compose exec -T ollama ollama pull llama3.1:8b-instruct-q4_0
    
    echo -e "${GREEN}✓ Modelos descargados${NC}"
    echo ""
}

# ============================================
# INICIAR TODOS LOS SERVICIOS
# ============================================

start_all_services() {
    echo -e "${YELLOW}Iniciando todos los servicios...${NC}"
    
    # Backend y servicios principales
    docker-compose up -d litellm rag-backend indexer openwebui
    
    echo "Esperando a que los servicios estén listos..."
    sleep 30
    
    # Verificar salud
    echo "Estado de servicios:"
    docker-compose ps
    
    echo -e "${GREEN}✓ Todos los servicios iniciados${NC}"
    echo ""
}

# ============================================
# VERIFICAR INSTALACIÓN
# ============================================

verify_installation() {
    echo -e "${YELLOW}Verificando instalación...${NC}"
    
    # Health check del backend
    if curl -f http://localhost:8000/health &>/dev/null; then
        echo -e "${GREEN}✓ Backend API respondiendo${NC}"
    else
        echo -e "${RED}❌ Backend API no responde${NC}"
    fi
    
    # Verificar Qdrant
    if curl -f http://localhost:6333/collections/documentos &>/dev/null; then
        echo -e "${GREEN}✓ Qdrant operativo${NC}"
    else
        echo -e "${RED}❌ Qdrant no responde${NC}"
    fi
    
    # Verificar LiteLLM
    if curl -f http://localhost:4000/health &>/dev/null; then
        echo -e "${GREEN}✓ LiteLLM proxy operativo${NC}"
    else
        echo -e "${RED}❌ LiteLLM no responde${NC}"
    fi
    
    echo ""
}

# ============================================
# RESUMEN FINAL
# ============================================

show_summary() {
    echo -e "${GREEN}"
    echo "============================================"
    echo "  ✅ INSTALACIÓN COMPLETADA"
    echo "============================================"
    echo -e "${NC}"
    
    echo "Servicios disponibles:"
    echo ""
    echo "  🌐 OpenWebUI:       http://localhost:3000"
    echo "  🔌 API Backend:     http://localhost:8000"
    echo "  📊 API Docs:        http://localhost:8000/docs"
    echo "  🗄️  Qdrant UI:       http://localhost:6333/dashboard"
    echo "  📦 MinIO Console:   http://localhost:9001"
    echo ""
    
    if [ "$HAS_GPU" = true ]; then
        echo -e "${GREEN}✓ GPU disponible - OCR acelerado activado${NC}"
    else
        echo -e "${YELLOW}⚠ Sin GPU - OCR funcionará en CPU (más lento)${NC}"
    fi
    
    echo ""
    echo "Próximos pasos:"
    echo ""
    echo "1. Abre OpenWebUI: http://localhost:3000"
    echo "2. Crea tu primer usuario"
    echo "3. Sube documentos o configura SharePoint sync"
    echo "4. ¡Comienza a chatear!"
    echo ""
    echo "Ver logs: docker-compose logs -f [servicio]"
    echo "Detener: docker-compose down"
    echo "Reiniciar: docker-compose restart"
    echo ""
    
    echo -e "${BLUE}Documentación completa en: docs/${NC}"
    echo ""
}

# ============================================
# MAIN
# ============================================

main() {
    check_requirements
    setup_env
    create_directories
    start_infrastructure
    init_database
    init_qdrant
    download_models
    start_all_services
    verify_installation
    show_summary
}

# Ejecutar
main
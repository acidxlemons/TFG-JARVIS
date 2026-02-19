#!/bin/bash
#scripts/backup.sh

# ============================================
# SCRIPT DE BACKUP
# Backup de Postgres, Qdrant y archivos
# ============================================

set -e

# Configuración
BACKUP_DIR="/backups/rag-system"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}Iniciando backup: ${TIMESTAMP}${NC}"

# Crear directorio de backups
mkdir -p ${BACKUP_DIR}

# ============================================
# BACKUP POSTGRES
# ============================================

echo -e "${YELLOW}Haciendo backup de Postgres...${NC}"

docker-compose exec -T postgres pg_dump -U rag_user rag_system | \
    gzip > ${BACKUP_DIR}/postgres_${TIMESTAMP}.sql.gz

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Postgres backup completado${NC}"
else
    echo -e "${RED}❌ Error en Postgres backup${NC}"
    exit 1
fi

# ============================================
# BACKUP QDRANT
# ============================================

echo -e "${YELLOW}Haciendo backup de Qdrant...${NC}"

# Crear snapshot
curl -X POST "http://localhost:6333/collections/documentos/snapshots" &>/dev/null

# Descargar snapshot
SNAPSHOT_NAME=$(curl -s "http://localhost:6333/collections/documentos/snapshots" | \
    python3 -c "import sys, json; print(json.load(sys.stdin)['result'][-1]['name'])")

curl -o ${BACKUP_DIR}/qdrant_${TIMESTAMP}.snapshot \
    "http://localhost:6333/collections/documentos/snapshots/${SNAPSHOT_NAME}"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Qdrant backup completado${NC}"
else
    echo -e "${RED}❌ Error en Qdrant backup${NC}"
fi

# ============================================
# BACKUP ARCHIVOS
# ============================================

echo -e "${YELLOW}Haciendo backup de archivos...${NC}"

tar -czf ${BACKUP_DIR}/files_${TIMESTAMP}.tar.gz \
    data/ \
    backend/app/cache/

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Archivos backup completado${NC}"
else
    echo -e "${RED}❌ Error en archivos backup${NC}"
fi

# ============================================
# LIMPIAR BACKUPS ANTIGUOS
# ============================================

echo -e "${YELLOW}Limpiando backups antiguos (>${RETENTION_DAYS} días)...${NC}"

find ${BACKUP_DIR} -type f -mtime +${RETENTION_DAYS} -delete

# ============================================
# RESUMEN
# ============================================

BACKUP_SIZE=$(du -sh ${BACKUP_DIR} | cut -f1)

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}Backup completado: ${TIMESTAMP}${NC}"
echo -e "${GREEN}============================================${NC}"
echo "Ubicación: ${BACKUP_DIR}"
echo "Tamaño total: ${BACKUP_SIZE}"
echo ""

# Listar backups recientes
echo "Backups recientes:"
ls -lh ${BACKUP_DIR} | tail -10
FROM python:3.11-slim

LABEL maintainer="TFG-RAG Project"
LABEL description="MCP Server para el Boletín Oficial del Estado (BOE)"

WORKDIR /app

# Copiar dependencias primero (cache de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Puerto 8010 para MCP (evita conflicto con backend en 8000)
EXPOSE 8010

# Ejecutar servidor MCP
CMD ["python", "mcp_boe_server.py"]

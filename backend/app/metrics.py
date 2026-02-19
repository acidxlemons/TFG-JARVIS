# backend/app/metrics.py
"""
Métricas Prometheus — Definiciones centralizadas

Todas las métricas de Prometheus se definen aquí para evitar duplicación
y poder importarlas desde cualquier módulo del backend.

Tipos de métricas:
- Counter: Cuenta eventos acumulativos (solo sube). Ej: total de requests.
- Histogram: Mide distribuciones (latencia, duración). Ej: tiempo de respuesta.
- Gauge: Mide valores que suben y bajan. Ej: documentos indexados.

Las métricas se exponen en el endpoint GET /metrics en formato Prometheus,
que es consumido por nuestra instancia de Prometheus cada 15 segundos y
visualizado en los dashboards de Grafana.

Uso:
    from app.metrics import http_requests_total, rag_comparison_queries_total
    http_requests_total.labels(method="POST", endpoint="/chat", status=200).inc()
"""

from prometheus_client import Counter, Histogram, Gauge


# ======================================================
# MÉTRICAS HTTP GENERALES
# ======================================================

http_requests_total = Counter(
    'http_requests_total',
    'Total de peticiones HTTP recibidas por el backend',
    ['method', 'endpoint', 'status']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'Duración de las peticiones HTTP en segundos',
    ['method', 'endpoint'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)


# ======================================================
# MÉTRICAS DE DOCUMENTOS
# ======================================================

documents_indexed_total = Gauge(
    'documents_indexed_total',
    'Total de documentos indexados en el sistema'
)


# ======================================================
# MÉTRICAS DEL SISTEMA
# ======================================================

app_info = Gauge(
    'app_info',
    'Información de la aplicación (versión)',
    ['version']
)
app_info.labels(version='2.1.0').set(1)  # Actualizado de 2.0.0 a 2.1.0 tras refactorización


# ======================================================
# MÉTRICAS RAG (Retrieval Augmented Generation)
# ======================================================

rag_filenames_detected_total = Counter(
    "rag_filenames_detected_total",
    "Veces que un nombre de documento fue detectado en la query del usuario",
    ["status", "count"]  # status: "found" | "none"
)

rag_comparison_queries_total = Counter(
    "rag_comparison_queries_total",
    "Queries identificadas como comparación (recuperación multi-documento)"
)

rag_listing_requests_total = Counter(
    "rag_listing_requests_total",
    "Total de peticiones de listado de documentos",
    ["type"]  # 'global' o 'filtered'
)

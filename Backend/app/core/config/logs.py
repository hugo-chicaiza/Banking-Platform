"""Formato y destino de los logs de toda la app.

Cada módulo solo hace `logger = logging.getLogger(__name__)`; aquí se decide cómo sale.
Todo va a stdout porque es lo que App Service guarda en Azure. Cada línea lleva el
traceId de la petición, el mismo que recibe el cliente en X-Request-Id y en los errores,
para poder buscar en los logs lo que pasó con una petición concreta.
"""

import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Lo fija TraceIdMiddleware al inicio de cada petición. Fuera de una petición
# (arranque, tareas de fondo) queda en "-".
trace_id_actual: ContextVar[str] = ContextVar("trace_id", default="-")

_NOMBRE_HANDLER = "banking-platform"

# Uvicorn y gunicorn traen sus propios handlers con otro formato; se quitan para que
# sus mensajes pasen por el mismo formato que los de la app.
_LOGGERS_SERVIDOR = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "gunicorn.error",
    "gunicorn.access",
)


class _AgregarTraceId(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_actual.get()
        return True


class _Formato(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Un salto de línea dentro de un valor (por ejemplo una ruta con %0A) partiría
        # la línea y permitiría inventar entradas falsas en el log.
        mensaje = record.getMessage().replace("\r", "\\r").replace("\n", "\\n")
        hora = datetime.fromtimestamp(record.created, UTC).isoformat(
            timespec="milliseconds"
        )
        trace_id = getattr(record, "trace_id", "-")
        linea = f"{hora} {record.levelname} {record.name} trace={trace_id} {mensaje}"
        if record.exc_info:
            linea += "\n" + self.formatException(record.exc_info)
        return linea


def configurar_logging(nivel: str) -> None:
    raiz = logging.getLogger()
    # Con --reload o en pruebas el módulo se importa varias veces; sin esta revisión
    # cada línea saldría repetida.
    if not any(h.get_name() == _NOMBRE_HANDLER for h in raiz.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_NOMBRE_HANDLER)
        handler.setFormatter(_Formato())
        handler.addFilter(_AgregarTraceId())
        raiz.addHandler(handler)
    raiz.setLevel(nivel)

    for nombre in _LOGGERS_SERVIDOR:
        servidor = logging.getLogger(nombre)
        servidor.handlers.clear()
        servidor.propagate = True
    # TraceIdMiddleware ya registra cada petición. El log de uvicorn se apaga porque
    # duplicaría la línea e incluye el query string, que puede traer cédulas o nombres.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # httpx (WorkOS, buró) escribe en INFO cada URL completa, con su query string
    for cliente_http in ("httpx", "httpcore"):
        logging.getLogger(cliente_http).setLevel(logging.WARNING)

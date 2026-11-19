"""Formato y destino de los logs de toda la app.

Cada módulo solo hace `logger = logging.getLogger(__name__)`; aquí se decide cómo sale.
Todo va a stdout porque es lo que App Service guarda en Azure. Cada línea lleva el
traceId de la petición, el mismo que recibe el cliente en X-Request-Id y en los errores,
para poder buscar en los logs lo que pasó con una petición concreta.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Literal

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


# Lo que nunca debe quedar en un log aunque un módulo lo pase por error (E0-13). Los
# módulos no deben registrar estos datos; esto es la última barrera, no la regla.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRETO = re.compile(r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{8,}\b")
_CLAVE_VALOR = re.compile(
    r"(?i)\b(password|contrase(?:ñ|n)a|clave|secret|token|api[_-]?key|pin|cookie)"
    r"(\s*[=:]\s*)([^\s,;&]+)"
)
_DIGITOS = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")


def _luhn(digitos: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digitos)):
        n = int(d)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _pan(coincidencia: re.Match[str]) -> str:
    digitos = re.sub(r"\D", "", coincidencia.group(0))
    if 13 <= len(digitos) <= 19 and _luhn(digitos):
        return f"[PAN ****{digitos[-4:]}]"
    return coincidencia.group(0)


def enmascarar(texto: str) -> str:
    """Quita tokens, secretos, valores de claves y números de tarjeta de un texto."""
    texto = _JWT.sub("[token]", texto)
    texto = _BEARER.sub("Bearer [token]", texto)
    texto = _SECRETO.sub("[secreto]", texto)
    texto = _CLAVE_VALOR.sub(lambda m: f"{m.group(1)}{m.group(2)}[oculto]", texto)
    return _DIGITOS.sub(_pan, texto)


class _AgregarTraceId(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_actual.get()
        return True


class _Formato(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Un salto de línea dentro de un valor (por ejemplo una ruta con %0A) partiría
        # la línea y permitiría inventar entradas falsas en el log.
        mensaje = (
            enmascarar(record.getMessage()).replace("\r", "\\r").replace("\n", "\\n")
        )
        hora = datetime.fromtimestamp(record.created, UTC).isoformat(
            timespec="milliseconds"
        )
        trace_id = getattr(record, "trace_id", "-")
        linea = f"{hora} {record.levelname} {record.name} trace={trace_id} {mensaje}"
        if record.exc_info:
            linea += "\n" + enmascarar(self.formatException(record.exc_info))
        return linea


class _FormatoJson(logging.Formatter):
    """Una línea JSON por registro (LOG_FORMATO=json), para herramientas de búsqueda."""

    def format(self, record: logging.LogRecord) -> str:
        datos = {
            "hora": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "nivel": record.levelname,
            "origen": record.name,
            "traceId": getattr(record, "trace_id", "-"),
            "mensaje": enmascarar(record.getMessage()),
        }
        if record.exc_info:
            datos["excepcion"] = enmascarar(self.formatException(record.exc_info))
        return json.dumps(datos, ensure_ascii=False)


def configurar_logging(nivel: str, formato: Literal["texto", "json"] = "texto") -> None:
    raiz = logging.getLogger()
    # Con --reload o en pruebas el módulo se importa varias veces; sin esta revisión
    # cada línea saldría repetida.
    if not any(h.get_name() == _NOMBRE_HANDLER for h in raiz.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_NOMBRE_HANDLER)
        handler.setFormatter(_FormatoJson() if formato == "json" else _Formato())
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

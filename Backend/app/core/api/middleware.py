"""Agrega X-Request-Id a las respuestas y deja una línea de log por petición.

El X-Request-Id es el mismo traceId de los errores (F-04) y de cada línea de log.
"""

import ipaddress
import logging
import re
import time
import uuid
from collections.abc import Mapping
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config.logs import trace_id_actual

logger = logging.getLogger("app.peticiones")

_ID_VALIDO = re.compile(r"[A-Za-z0-9._-]{1,64}")


def obtener_trace_id(scope: Mapping[str, Any]) -> str:
    """Si el middleware no está instalado, como en algunas pruebas, se genera uno."""
    return scope.get("state", {}).get("trace_id") or str(uuid.uuid4())


def ip_cliente(scope: Scope) -> str:
    """IP que entrega uvicorn. Si no es válida, no se usa como clave ni va al log.

    En Azure será la del proxy hasta que se configure FORWARDED_ALLOW_IPS.
    """
    cliente = scope.get("client")
    try:
        return str(ipaddress.ip_address(cliente[0])) if cliente else "desconocida"
    except ValueError:
        return "desconocida"


def _id_de_la_peticion(scope: Scope) -> str:
    """Se respeta el id del cliente solo si es seguro ponerlo en cabeceras y logs."""
    for nombre, valor in scope["headers"]:
        if nombre == b"x-request-id":
            texto = valor.decode("latin1")
            if _ID_VALIDO.fullmatch(texto):
                return texto
            break
    return str(uuid.uuid4())


class TraceIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        trace_id = _id_de_la_peticion(scope)
        scope.setdefault("state", {})["trace_id"] = trace_id
        token = trace_id_actual.set(trace_id)
        inicio = time.perf_counter()
        # Si la app lanza una excepción sin responder, el cliente recibe un 500
        status = 500

        async def enviar(mensaje: Message) -> None:
            nonlocal status
            if mensaje["type"] == "http.response.start":
                status = mensaje["status"]
                MutableHeaders(scope=mensaje)["X-Request-Id"] = trace_id
            await send(mensaje)

        try:
            await self._app(scope, receive, enviar)
        finally:
            # Sin query string: en búsquedas puede llevar cédulas o nombres
            logger.info(
                "%s %s status=%s ms=%d ip=%s",
                scope["method"],
                scope["path"],
                status,
                (time.perf_counter() - inicio) * 1000,
                ip_cliente(scope),
            )
            trace_id_actual.reset(token)

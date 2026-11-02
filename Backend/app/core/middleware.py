"""Agrega X-Request-Id a las respuestas. Es el mismo traceId de los errores (F-04)."""

import re
import uuid
from collections.abc import Mapping
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_ID_VALIDO = re.compile(r"[A-Za-z0-9._-]{1,64}")


def obtener_trace_id(scope: Mapping[str, Any]) -> str:
    """Si el middleware no está instalado, como en algunas pruebas, se genera uno."""
    return scope.get("state", {}).get("trace_id") or str(uuid.uuid4())


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

        async def enviar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                MutableHeaders(scope=mensaje)["X-Request-Id"] = trace_id
            await send(mensaje)

        await self._app(scope, receive, enviar)

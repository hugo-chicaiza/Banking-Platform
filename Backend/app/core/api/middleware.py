"""Agrega X-Request-Id a las respuestas y deja una línea de log por petición.

El X-Request-Id es el mismo traceId de los errores (F-04) y de cada línea de log.
"""

import hmac
import ipaddress
import json
import logging
import re
import time
import uuid
from collections.abc import Mapping
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config.logs import trace_id_actual
from app.core.config.settings import get_settings

logger = logging.getLogger("app.peticiones")

_ID_VALIDO = re.compile(r"[A-Za-z0-9._-]{1,64}")


def obtener_trace_id(scope: Mapping[str, Any]) -> str:
    """Si el middleware no está instalado, como en algunas pruebas, se genera uno."""
    return scope.get("state", {}).get("trace_id") or str(uuid.uuid4())


CABECERA_IP = b"x-cliente-ip"
CABECERA_SECRETO = b"x-proxy-secreto"


def _valores(scope: Scope, nombre: bytes) -> list[bytes]:
    return [valor for clave, valor in scope.get("headers", []) if clave == nombre]


def viene_del_proxy(scope: Scope) -> bool:
    """True si la petición trae, una sola vez, el secreto compartido con el Worker.

    Comparación en tiempo constante. Sin secreto configurado nunca es True.
    """
    secreto = get_settings().proxy_secreto.get_secret_value().encode()
    valores = _valores(scope, CABECERA_SECRETO)
    return (
        bool(secreto) and len(valores) == 1 and hmac.compare_digest(valores[0], secreto)
    )


def _ip_valida(valor: str) -> str | None:
    try:
        return str(ipaddress.ip_address(valor.strip()))
    except ValueError:
        return None


def ip_cliente(scope: Scope) -> str:
    """IP del usuario para auditoría, logs y límite de peticiones (ASVS 4.1.3, 15.3.4).

    Solo se cree en X-Cliente-Ip si la petición viene del Worker (secreto válido): el
    Worker la toma de CF-Connecting-IP, que fija Cloudflare y el cliente no puede
    cambiar. En cualquier otro caso, la IP de la conexión. Una IP no válida no se usa
    como clave ni va al log.
    """
    if viene_del_proxy(scope):
        valores = _valores(scope, CABECERA_IP)
        ip = _ip_valida(valores[0].decode("latin1")) if len(valores) == 1 else None
        if ip:
            return ip
    cliente = scope.get("client")
    return (_ip_valida(str(cliente[0])) if cliente else None) or "desconocida"


class SoloProxyMiddleware:
    """Con PROXY_EXIGIDO, rechaza (403) lo que no llega por el Worker con el secreto: el
    backend solo atiende tráfico del proxy (ASVS 4.1.3; P4 FND-08).
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not viene_del_proxy(scope):
            cuerpo = json.dumps(
                {
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "code": "ORIGEN_NO_PERMITIDO",
                    "detail": "La petición no llegó por el canal autorizado.",
                    "traceId": obtener_trace_id(scope),
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/problem+json"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": cuerpo})
            return
        await self._app(scope, receive, send)


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
            # Sin query string: en búsquedas puede llevar cédulas o nombres. Usuario y
            # roles de WorkOS con que se atendió (las consultas no van a Auditoria)
            usuario = scope.get("state", {}).get("usuario")
            logger.info(
                "%s %s status=%s ms=%d ip=%s usuario=%s roles=%s",
                scope["method"],
                scope["path"],
                status,
                (time.perf_counter() - inicio) * 1000,
                ip_cliente(scope),
                getattr(usuario, "id_usuario", "-"),
                ",".join(getattr(usuario, "roles", ())) or "-",
            )
            trace_id_actual.reset(token)


# 1 año: el mínimo que aceptan las listas de precarga de los navegadores
HSTS = "max-age=31536000; includeSubDomains"


class HstsMiddleware:
    """Strict-Transport-Security en cada respuesta: el navegador usará solo HTTPS con la
    API, aunque alguien escriba http://. Azure termina el TLS antes de la app, así que la
    redirección de HTTP a HTTPS se activa en el portal (HTTPS Only), no aquí.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def enviar(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Strict-Transport-Security"] = HSTS
            await send(message)

        await self.app(scope, receive, enviar)

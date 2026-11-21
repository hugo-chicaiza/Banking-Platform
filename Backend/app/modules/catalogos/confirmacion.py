"""Código de confirmación para catálogos que pueden alterar la lógica de negocio.

Antes de crear o eliminar en esos catálogos (sistemas de amortización, canales,
denominaciones, tipos de movimiento de caja) el backend emite un código de 4
caracteres con una advertencia; la operación se acepta solo si vuelve el mismo código
con su token, para el mismo usuario y catálogo, antes de que venza (5 minutos).

El token es un HMAC sin estado (sirve con varias instancias del App Service): lleva el
usuario, el catálogo, el vencimiento y el hash del código, nunca el código en claro.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from functools import lru_cache

from app.core.api.errors import problema
from app.core.config.settings import get_settings

CATALOGOS_CON_CONFIRMACION = frozenset(
    {"sistemas-amortizacion", "canales", "denominaciones", "tipos-movimiento-caja"}
)
ADVERTENCIA = (
    "Este cambio puede alterar la lógica de negocio de la plataforma. "
    "Para continuar, ingrese el código de confirmación."
)
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I para leerlo bien
_LARGO = 4
_VIGENCIA_S = 300


@lru_cache
def _clave(semilla: str) -> bytes:
    # Derivada de un secreto que ya existe en cada entorno; sin él, una por proceso
    base = semilla or secrets.token_hex(32)
    return hashlib.sha256(f"confirmacion-catalogos:{base}".encode()).digest()


def _firma(datos: bytes) -> str:
    clave = _clave(get_settings().workos_cookie_password.get_secret_value())
    return hmac.new(clave, datos, hashlib.sha256).hexdigest()


def _hash_codigo(codigo: str) -> str:
    return hashlib.sha256(codigo.strip().upper().encode()).hexdigest()


def emitir(
    id_usuario: str, catalogo: str, ahora: float | None = None
) -> dict[str, object]:
    codigo = "".join(secrets.choice(_ALFABETO) for _ in range(_LARGO))
    vence = int((ahora or time.time()) + _VIGENCIA_S)
    datos = json.dumps(
        {"u": id_usuario, "c": catalogo, "v": vence, "h": _hash_codigo(codigo)},
        separators=(",", ":"),
    ).encode()
    token = f"{base64.urlsafe_b64encode(datos).decode()}.{_firma(datos)}"
    return {
        "codigo": codigo,
        "token": token,
        "venceEnSegundos": _VIGENCIA_S,
        "advertencia": ADVERTENCIA,
    }


def exigir(
    id_usuario: str,
    catalogo: str,
    token: str | None,
    codigo: str | None,
    ahora: float | None = None,
) -> None:
    """428 si falta la confirmación; 422 si no coincide, venció o es de otro usuario o
    catálogo."""
    if catalogo not in CATALOGOS_CON_CONFIRMACION:
        return
    if not token or not codigo:
        raise problema(
            428,
            "CONFIRMACION_REQUERIDA",
            "Este cambio requiere el código de confirmación.",
        )
    invalido = problema(
        422,
        "CONFIRMACION_INVALIDA",
        "El código de confirmación no es válido o venció. Pide uno nuevo.",
    )
    try:
        cuerpo, firma = token.rsplit(".", 1)
        datos = base64.urlsafe_b64decode(cuerpo.encode())
        if not hmac.compare_digest(firma, _firma(datos)):
            raise invalido
        contenido = json.loads(datos)
    except (ValueError, TypeError):
        raise invalido from None
    if (
        contenido.get("u") != id_usuario
        or contenido.get("c") != catalogo
        or int(contenido.get("v", 0)) < (ahora or time.time())
        or not hmac.compare_digest(contenido.get("h", ""), _hash_codigo(codigo))
    ):
        raise invalido

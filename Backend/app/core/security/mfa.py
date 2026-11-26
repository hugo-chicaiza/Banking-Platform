"""Segundo factor (TOTP de WorkOS/AuthKit) ligado a UNA acción concreta.

Uso desde cualquier módulo que deba confirmar una operación sensible con MFA:

    desafio = mfa.pedir_desafio(usuario, "clientes.revelar", recurso)   # paso 1
    ...el usuario escribe el código de su app...
    if not mfa.verificar(usuario, "clientes.revelar", recurso,          # paso 2
                         id_desafio, comprobante, codigo):
        raise problema(422, "MFA_INVALIDO", ...)

El desafío de WorkOS no guarda contexto: por sí solo, un código válido obtenido para
una acción serviría para otra. Por eso el paso 1 devuelve además un **comprobante**
HMAC-SHA256 que ata el desafío al usuario, a su sesión, a la acción, al recurso y a un
vencimiento. El paso 2 rehace la firma con la acción y el recurso de la petición en
curso; si algo difiere (otra acción, otro recurso, otra sesión, otro usuario, vencido)
se rechaza antes de llamar a WorkOS. WorkOS invalida el desafío tras usarlo (uso único).

La clave del comprobante se deriva con HKDF de WORKOS_COOKIE_PASSWORD con un contexto
propio (separación de claves, ASVS 11.x); sin ese secreto, el MFA falla cerrado (503).
Nunca se registran el código ni el comprobante. ASVS 6.3.3, 6.6.x, 11.4, 16.3.1.
"""

import base64
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import HTTPException
from workos.exceptions import (
    BadRequestException,
    BaseRequestException,
    NotFoundException,
)

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.core.security.auth import Usuario, get_workos

logger = logging.getLogger(__name__)

VIGENCIA_SEGUNDOS = 300
_CONTEXTO_CLAVE = b"enquo/mfa-comprobante/v1"


@dataclass(frozen=True)
class Desafio:
    id_desafio: str
    comprobante: str
    expira_en: str


def _no_disponible() -> HTTPException:
    return problema(
        503,
        "MFA_NO_DISPONIBLE",
        "No pudimos comprobar el segundo factor; intenta otra vez.",
    )


def _clave() -> bytes:
    secreto = get_settings().workos_cookie_password.get_secret_value()
    if not secreto:
        raise _no_disponible()
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=_CONTEXTO_CLAVE
    ).derive(secreto.encode())


def _firma(
    usuario: Usuario, accion: str, recurso: str, id_desafio: str, expira: int
) -> str:
    mensaje = "\n".join(
        (
            "v1",
            usuario.id_usuario,
            usuario.id_sesion or "",
            accion,
            recurso,
            id_desafio,
            str(expira),
        )
    ).encode()
    mac = hmac.new(_clave(), mensaje, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def _factores(usuario: Usuario) -> list[str]:
    try:
        factores = get_workos().user_management.list_auth_factors(
            user_id=usuario.id_usuario
        )
        return [f.id for f in factores if getattr(f, "type", None) == "totp"]
    except (BaseRequestException, httpx.HTTPError) as error:
        logger.warning("mfa: factores no disponibles tipo=%s", type(error).__name__)
        raise _no_disponible() from None


def pedir_desafio(usuario: Usuario, accion: str, recurso: str) -> Desafio:
    """Desafío para el factor TOTP del usuario, válido solo para (acción, recurso)."""
    factores = _factores(usuario)
    if not factores:
        raise problema(
            409,
            "MFA_NO_CONFIGURADO",
            "Configura la verificación en dos pasos de tu cuenta para continuar.",
        )
    try:
        reto = get_workos().mfa.challenge_factor(authentication_factor_id=factores[0])
    except (BaseRequestException, httpx.HTTPError) as error:
        logger.warning("mfa: desafío no creado tipo=%s", type(error).__name__)
        raise _no_disponible() from None
    expira = int(time.time()) + VIGENCIA_SEGUNDOS
    # Nunca se devuelve reto.code: solo el id y el comprobante.
    return Desafio(
        id_desafio=reto.id,
        comprobante=f"{expira}.{_firma(usuario, accion, recurso, reto.id, expira)}",
        expira_en=datetime.fromtimestamp(expira, UTC).isoformat(),
    )


def _comprobante_valido(
    usuario: Usuario, accion: str, recurso: str, id_desafio: str, comprobante: str
) -> bool:
    expira_texto, _, firma = comprobante.partition(".")
    if not expira_texto.isdigit() or not firma:
        return False
    expira = int(expira_texto)
    if expira < time.time():
        return False
    esperada = _firma(usuario, accion, recurso, id_desafio, expira)
    return hmac.compare_digest(firma, esperada)


def verificar(
    usuario: Usuario,
    accion: str,
    recurso: str,
    id_desafio: str | None,
    comprobante: str | None,
    codigo: str | None,
) -> bool:
    """True solo si el código es válido para ESTA acción y ESTE recurso del usuario."""
    if not id_desafio or not comprobante or not codigo:
        return False
    if not _comprobante_valido(usuario, accion, recurso, id_desafio, comprobante):
        return False  # desafío pedido para otra acción, recurso, sesión o vencido
    factores = set(_factores(usuario))
    try:
        respuesta = get_workos().mfa.verify_challenge(
            authentication_challenge_id=id_desafio, code=codigo
        )
    except (BadRequestException, NotFoundException):
        return False  # código vencido, ya usado o desafío inexistente
    except (BaseRequestException, httpx.HTTPError) as error:
        logger.warning("mfa: verificación no disponible tipo=%s", type(error).__name__)
        raise _no_disponible() from None
    return bool(respuesta.valid) and (
        respuesta.challenge.authentication_factor_id in factores
    )

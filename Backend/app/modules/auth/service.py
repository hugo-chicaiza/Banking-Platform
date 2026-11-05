"""Reglas de AUT-01..04 sobre WorkOS AuthKit (patrón BFF).

WorkOS es la fuente de usuarios, roles y sesiones; aquí no hay SQL, por eso el módulo
no tiene repository.py. Nunca se registran tokens, codes ni cookies en logs.
"""

import base64
import binascii
import logging
import re
import secrets

import httpx
from fastapi import HTTPException
from workos.exceptions import BaseRequestException, ServerException

from app.core.security import audit
from app.core.security.auth import (
    SesionValida,
    Usuario,
    renovar_sesion,
    validar_sesion,
)
from app.integrations.workos_client import (
    get_cookie_password,
    get_redirect_uri,
    get_workos,
)
from app.modules.auth.schemas import UsuarioSesion

logger = logging.getLogger(__name__)

# Ruta interna del FE: empieza con "/"
_RUTA_INTERNA = re.compile(r"^/(?![/\\])[!-\[\]-~]{0,511}$")
_RUTA_POR_DEFECTO = "/"
_RUTA_LOGIN = "/login"
_TABLA_AUDITORIA = "WorkOS.Sesiones"


def ruta_segura(return_to: str | None) -> str:
    """return_to solo puede ser una ruta del FE; si no, se usa "/"."""
    if return_to and _RUTA_INTERNA.fullmatch(return_to):
        return return_to
    return _RUTA_POR_DEFECTO


def _url_error(origen: str, code: str) -> str:
    return f"{origen}{_RUTA_LOGIN}?error={code}"


def _auditar(
    accion: str, resultado: audit.Resultado, descripcion: str, ip: str | None
) -> None:
    # UsuarioID tiene FK a Organizacion.Usuarios y el usuario vive en WorkOS: va NULL
    # y el id de WorkOS queda en la descripción
    audit.registrar(
        audit.EventoAuditoria(
            accion=accion,
            tabla=_TABLA_AUDITORIA,
            id_registro=None,
            resultado=resultado,
            usuario=None,
            ip=ip,
            descripcion=descripcion,
        )
    )


# --- AUT-01 login + callback -------------------------------------------------------


def iniciar_login(return_to: str | None, origen: str) -> tuple[str, str]:
    """Devuelve la URL del Hosted UI y el valor de la cookie de state.

    La cookie guarda el state y la ruta de regreso; el callback los compara.
    """
    state = secrets.token_urlsafe(32)
    # Sin el relleno "=": así el valor de la cookie no necesita comillas
    ruta = ruta_segura(return_to).encode()
    destino = base64.urlsafe_b64encode(ruta).decode().rstrip("=")
    url = get_workos().user_management.get_authorization_url(
        provider="authkit", redirect_uri=get_redirect_uri(origen), state=state
    )
    return url, f"{state}.{destino}"


def _leer_cookie_state(valor: str | None) -> tuple[str, str] | None:
    if not valor or "." not in valor:
        return None
    state, destino = valor.split(".", 1)
    try:
        relleno = "=" * (-len(destino) % 4)
        ruta = base64.urlsafe_b64decode((destino + relleno).encode()).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    return state, ruta_segura(ruta)


def completar_login(
    code: str | None,
    state: str | None,
    error: str | None,
    cookie_state: str | None,
    ip: str | None,
    user_agent: str | None,
    origen: str,
) -> tuple[str, str | None]:
    """Canjea el code. Devuelve a dónde redirigir y la sesión sellada (None si falló)."""
    guardado = _leer_cookie_state(cookie_state)

    def fallo(code_error: str, motivo: str) -> tuple[str, None]:
        logger.warning("auth: login fallido motivo=%s", motivo)
        _auditar("LOGIN", "Fallido", f"AUT-01 Inicio de sesión {code_error}", ip)
        return _url_error(origen, code_error), None

    if error:
        # El usuario canceló en el Hosted UI o WorkOS rechazó la solicitud
        return fallo("LOGIN_CANCELADO", "error_en_callback")
    if (
        not code
        or not state
        or guardado is None
        or not secrets.compare_digest(state, guardado[0])
    ):
        return fallo("SOLICITUD_INVALIDA", "state")

    try:
        resultado = get_workos().user_management.authenticate_with_code(
            code=code,
            session={"seal_session": True, "cookie_password": get_cookie_password()},
            ip_address=ip,
            user_agent=user_agent,
        )
    except (ServerException, httpx.HTTPError) as exc:
        logger.error("auth: WorkOS no disponible tipo=%s", type(exc).__name__)
        return _url_error(origen, "AUTENTICACION_NO_DISPONIBLE"), None
    except BaseRequestException as exc:
        # code y request_id de WorkOS sirven para soporte y no son secretos
        logger.warning(
            "auth: WorkOS rechazó el code code=%s request_id=%s",
            exc.code or exc.error,
            exc.request_id,
        )
        return fallo("CREDENCIALES_INVALIDAS", "code")

    if not resultado.sealed_session:
        return fallo("CREDENCIALES_INVALIDAS", "sin_sesion")
    _auditar(
        "LOGIN",
        "Exitoso",
        f"AUT-01 Inicio de sesión workos_user={resultado.user.id}",
        ip,
    )
    logger.info("auth: login usuario=%s", resultado.user.id)
    return f"{origen}{guardado[1]}", resultado.sealed_session


# --- AUT-02 refresh ----------------------------------------------------------------


def refrescar(sellada: str | None) -> SesionValida | None:
    """Renueva el access token aunque no haya vencido. None si la sesión no sirve."""
    return renovar_sesion(sellada) if sellada else None


# --- AUT-03 logout -----------------------------------------------------------------


def cerrar_sesion(sellada: str | None, ip: str | None, origen: str) -> str:
    """URL a la que el FE debe navegar. Idempotente: sin sesión devuelve /login."""
    login = f"{origen}{_RUTA_LOGIN}"
    if not sellada:
        return login
    # Si el access token venció hay que renovarlo para conocer el id de la sesión
    try:
        sesion = validar_sesion(sellada)
    except HTTPException:
        # WorkOS no responde: la cookie se borra igual y el FE va al login
        sesion = None
    if sesion is None:
        _auditar("LOGOUT", "Fallido", "AUT-03 Cierre de sesión sin sesión válida", ip)
        return login
    url = get_workos().user_management.get_logout_url(
        session_id=sesion.usuario.id_sesion, return_to=login
    )
    _auditar(
        "LOGOUT",
        "Exitoso",
        f"AUT-03 Cierre de sesión workos_user={sesion.usuario.id_usuario}",
        ip,
    )
    return url


# --- AUT-04 me ---------------------------------------------------------------------


def perfil(usuario: Usuario) -> UsuarioSesion:
    return UsuarioSesion(
        id_usuario=usuario.id_usuario,
        nombre=usuario.nombre,
        email=usuario.email,
        id_organizacion=usuario.id_organizacion,
        roles=list(usuario.roles),
        permisos=list(usuario.permisos),
        id_agencia=usuario.id_agencia,
    )

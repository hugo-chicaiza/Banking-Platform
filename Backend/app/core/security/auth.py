"""Autenticación por sesión de WorkOS AuthKit (F-03), patrón BFF.

El navegador solo guarda la cookie `__Host-session`: la sesión de WorkOS (access token,
refresh token y usuario) cifrada con WORKOS_COOKIE_PASSWORD. JavaScript no la puede
leer y el FE nunca maneja tokens.

Dependencias:

- `UsuarioActual`: valida la cookie, renueva el access token si venció (y reescribe
  la cookie) y entrega el usuario. En POST/PUT/PATCH/DELETE además verifica el origen
  de la petición (CSRF). Responde 401 o 403.
- `require_roles("CAJERO", ...)`: igual que la anterior y además exige un rol (403).
- `require_auth`: la que declaran todos los routers. Por ahora NO valida nada; para
  activar la autenticación en general para el backend basta con cambiar su cuerpo (ver abajo).
"""

import hashlib
import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import APIKeyCookie
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError
from workos.types.user_management.session import (
    AuthenticateWithSessionCookieErrorResponse,
    AuthenticateWithSessionCookieFailureReason,
    AuthenticateWithSessionCookieSuccessResponse,
    RefreshWithSessionCookieErrorResponse,
    RefreshWithSessionCookieSuccessResponse,
)

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.integrations.workos_client import (
    get_cookie_password,
    get_frontend_url,
    get_workos,
)

logger = logging.getLogger(__name__)

# Roles del sistema. En WorkOS se crean con estos slugs (en minúsculas también sirve:
# "cajero" o "aprobador-credito" se leen como CAJERO y APROBADOR_CREDITO).
ROLES = (
    "ADMIN",
    "ASESOR",
    "CAJERO",
    "SUPERVISOR",
    "APROBADOR_CREDITO",
    "CONTADOR",
    "AUDITOR",
)

# __Host-: el navegador exige Secure y Path=/ y no permite Domain, así un subdominio
# no puede plantar ni pisar la cookie.
COOKIE_SESION = "__Host-session"
DURACION_SESION = 8 * 60 * 60  # AUT-01: 8 h. Igualar a la sesión configurada en WorkOS

_METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}
_SITIOS_PROPIOS = {"same-origin", "none"}
_LONGITUD_AGENCIA = 3
# Peticiones paralelas con el token vencido comparten una sola renovación: WorkOS
# acepta cada refresh token una sola vez
_VIGENCIA_RENOVACION = 30.0
_renovaciones: dict[str, tuple[float, RefreshWithSessionCookieSuccessResponse]] = {}
_candado_renovacion = threading.Lock()

# Solo documenta la cookie en /docs; el valor se lee igual que con request.cookies
_cookie = APIKeyCookie(
    name=COOKIE_SESION, auto_error=False, description="Sesión de WorkOS AuthKit"
)

Exito = AuthenticateWithSessionCookieSuccessResponse


@dataclass(frozen=True)
class Usuario:
    """Usuario autenticado, tomado de la sesión de WorkOS."""

    id_usuario: str  # id de WorkOS ("user_01...")
    id_sesion: str  # sid: la sesión que se cierra en el logout
    id_organizacion: str | None
    nombre: str
    email: str
    roles: tuple[str, ...]
    permisos: tuple[str, ...]
    id_agencia: str | None  # metadato "idAgencia" del usuario en WorkOS


@dataclass(frozen=True)
class SesionValida:
    usuario: Usuario
    # Si el access token venció y se renovó, la cookie nueva que hay que guardar
    sellada_nueva: str | None


# --- Cookies ---------------------------------------------------------------------


def guardar_cookie_sesion(response: Response, sellada: str) -> None:
    # HttpOnly: JavaScript no la lee (XSS). Secure: solo HTTPS (http://localhost cuenta
    # como seguro en Chrome y Firefox). Lax: viaja al volver del Hosted UI, pero no en
    # POST desde otros sitios.
    response.set_cookie(
        COOKIE_SESION,
        sellada,
        max_age=DURACION_SESION,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def borrar_cookie_sesion(response: Response) -> None:
    response.delete_cookie(
        COOKIE_SESION, path="/", secure=True, httponly=True, samesite="lax"
    )


def no_autenticado(borrar_cookie: bool = False) -> HTTPException:
    headers: dict[str, str] = {}
    if borrar_cookie:
        # La respuesta de error es otra, así que el Set-Cookie va en la excepción
        temporal = Response()
        borrar_cookie_sesion(temporal)
        headers["Set-Cookie"] = temporal.headers["set-cookie"]
    return HTTPException(
        status_code=401,
        detail={"code": "NO_AUTENTICADO", "message": "Inicie sesión para continuar."},
        headers=headers or None,
    )


def _no_disponible() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "AUTENTICACION_NO_DISPONIBLE",
            "message": "El servicio de autenticación no está disponible.",
        },
    )


# --- CSRF ------------------------------------------------------------------------


def verificar_origen(request: Request) -> None:
    """Protección CSRF de las peticiones que modifican datos.

    Como la sesión va en una cookie, el navegador la manda sola. Un POST que no viene
    de FRONTEND_URL se rechaza con 403. Sin Origin ni Sec-Fetch-Site no es un
    navegador (Postman, curl), y ahí no hay CSRF posible.
    """
    if request.method in _METODOS_SEGUROS:
        return
    origen = request.headers.get("origin")
    sitio = request.headers.get("sec-fetch-site")
    if origen is None and (sitio is None or sitio in _SITIOS_PROPIOS):
        return
    if origen == get_frontend_url():
        return
    logger.warning("auth: origen rechazado origin=%s sec_fetch_site=%s", origen, sitio)
    raise HTTPException(
        status_code=403,
        detail={
            "code": "ORIGEN_NO_PERMITIDO",
            "message": "La solicitud no viene de un origen permitido.",
        },
    )


# --- Sesión ----------------------------------------------------------------------


def normalizar_roles(roles: Sequence[str] | None, rol: str | None) -> tuple[str, ...]:
    """Lee `roles` o, si no viene, `role`. Ignora los que no son del sistema, como el
    "member" que WorkOS asigna por defecto.
    """
    crudos = list(roles) if roles else [rol]
    resultado: list[str] = []
    for crudo in crudos:
        if not isinstance(crudo, str):
            continue
        nombre = crudo.strip().upper().replace("-", "_")
        if nombre in ROLES and nombre not in resultado:
            resultado.append(nombre)
    return tuple(resultado)


def _agencia(metadatos: Mapping[str, str] | None) -> str | None:
    agencia = (metadatos or {}).get("idAgencia")
    if (
        isinstance(agencia, str)
        and len(agencia) == _LONGITUD_AGENCIA
        and agencia.isdigit()
    ):
        return agencia
    return None


def _usuario(sesion: Exito) -> Usuario:
    datos = sesion.user
    nombre = " ".join(p for p in (datos.first_name, datos.last_name) if p)
    return Usuario(
        id_usuario=datos.id,
        id_sesion=sesion.session_id,
        id_organizacion=sesion.organization_id,
        nombre=nombre or datos.email,
        email=datos.email,
        roles=normalizar_roles(sesion.roles, sesion.role),
        permisos=tuple(sesion.permissions or ()),
        id_agencia=_agencia(datos.metadata),
    )


def _renovar(
    sellada: str,
) -> RefreshWithSessionCookieSuccessResponse | RefreshWithSessionCookieErrorResponse:
    clave = hashlib.sha256(sellada.encode()).hexdigest()
    with _candado_renovacion:
        ahora = time.monotonic()
        for vieja in [
            k for k, (t, _) in _renovaciones.items() if ahora - t > _VIGENCIA_RENOVACION
        ]:
            del _renovaciones[vieja]
        if clave in _renovaciones:
            return _renovaciones[clave][1]
        sesion = get_workos().user_management.load_sealed_session(
            sealed_session=sellada, cookie_password=get_cookie_password()
        )
        resultado = sesion.refresh()
        if isinstance(resultado, RefreshWithSessionCookieSuccessResponse):
            _renovaciones[clave] = (ahora, resultado)
        else:
            # El motivo puede ser un error de WorkOS; no incluye tokens
            logger.info(
                "auth: no se pudo renovar la sesión motivo=%s", resultado.reason
            )
        return resultado


def renovar_sesion(sellada: str) -> SesionValida | None:
    """Pide a WorkOS un access token nuevo. None si la sesión ya no sirve."""
    resultado = _renovar(sellada)
    if not isinstance(resultado, RefreshWithSessionCookieSuccessResponse):
        return None
    return SesionValida(_usuario(resultado), resultado.sealed_session)


def validar_sesion(sellada: str) -> SesionValida | None:
    """Descifra la cookie y valida el access token; si venció, lo renueva.

    None si la cookie no sirve; 503 si no se pueden descargar las llaves de WorkOS.
    """
    sesion = get_workos().user_management.load_sealed_session(
        sealed_session=sellada, cookie_password=get_cookie_password()
    )
    try:
        resultado = sesion.authenticate()
    except PyJWKClientConnectionError:
        logger.error("auth: no se pudieron descargar las llaves JWKS de WorkOS")
        raise _no_disponible() from None
    except PyJWKClientError as exc:
        logger.info("auth: token con llave desconocida tipo=%s", type(exc).__name__)
        return None

    if isinstance(resultado, AuthenticateWithSessionCookieErrorResponse):
        # INVALID_JWT incluye el access token vencido: se intenta renovar
        if resultado.reason != AuthenticateWithSessionCookieFailureReason.INVALID_JWT:
            return None
        return renovar_sesion(sellada)
    return SesionValida(_usuario(resultado), None)


# --- Dependencias ----------------------------------------------------------------


def usuario_actual(
    request: Request,
    response: Response,
    sellada: Annotated[str | None, Depends(_cookie)],
) -> Usuario:
    """401 sin sesión válida; 403 si un POST/PUT/PATCH/DELETE viene de otro origen."""
    verificar_origen(request)
    if not sellada:
        raise no_autenticado()
    valida = validar_sesion(sellada)
    if valida is None:
        raise no_autenticado(borrar_cookie=True)
    if valida.sellada_nueva:
        guardar_cookie_sesion(response, valida.sellada_nueva)
    return valida.usuario


# Para recibir el usuario en un endpoint: def ver(usuario: UsuarioActual)
UsuarioActual = Annotated[Usuario, Depends(usuario_actual)]


def id_usuario_auditoria(usuario: UsuarioActual) -> int:
    """Resuelve una identidad ya autenticada usando vínculos del servidor."""
    id_interno = get_settings().workos_audit_user_ids.get(usuario.id_usuario)
    if id_interno is None:
        raise problema(
            403,
            "USUARIO_SIN_VINCULO_AUDITORIA",
            "El usuario no tiene un vínculo de auditoría configurado.",
        )
    return id_interno


UsuarioAuditoria = Annotated[int, Depends(id_usuario_auditoria)]


def require_auth() -> None:
    """Dependencia que declaran todos los routers. Por ahora no valida nada.

    TODO(F-03): para exigir sesión en todo el backend, reemplazar por:

        def require_auth(usuario: UsuarioActual) -> Usuario:
            return usuario
    """


def require_roles(*permitidos: str) -> Callable[..., Usuario]:
    """Dependencia que responde 403 si el usuario no tiene ninguno de los roles."""
    desconocidos = set(permitidos) - set(ROLES)
    if not permitidos or desconocidos:
        raise ValueError(f"Roles no válidos: {sorted(desconocidos)}")

    def verificar(usuario: UsuarioActual) -> Usuario:
        if not set(usuario.roles) & set(permitidos):
            logger.warning(
                "auth: acceso denegado usuario=%s roles=%s requeridos=%s",
                usuario.id_usuario,
                ",".join(usuario.roles),
                ",".join(permitidos),
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "SIN_PERMISO",
                    "message": "No tiene permiso para esta operación.",
                },
            )
        return usuario

    return verificar

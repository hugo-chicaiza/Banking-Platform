"""Autenticación por sesión de WorkOS AuthKit (F-03), patrón BFF.

El navegador solo guarda la cookie `__Host-session`: la sesión de WorkOS (access token,
refresh token y usuario) cifrada con WORKOS_COOKIE_PASSWORD. JavaScript no la puede
leer y el FE nunca maneja tokens.

Dependencias:

- `UsuarioActual`: valida la cookie, renueva el access token si venció (y reescribe
  la cookie) y entrega el usuario. En POST/PUT/PATCH/DELETE además verifica el origen
  de la petición (CSRF). Responde 401 o 403.
- `require_roles("CAJERO", ...)`: igual que la anterior y además exige un rol (403).
- `require_auth`: la que declaran todos los routers. Exige una sesión válida (401).

Cada 401/403 de la API queda en Auditoria.Auditoria (`AccesoDenegadoMiddleware`).
"""

import hashlib
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, get_args

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import APIKeyCookie
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from workos.types.user_management.session import (
    AuthenticateWithSessionCookieErrorResponse,
    AuthenticateWithSessionCookieFailureReason,
    AuthenticateWithSessionCookieSuccessResponse,
    RefreshWithSessionCookieErrorResponse,
    RefreshWithSessionCookieSuccessResponse,
)

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.core.database.db import DbName, get_engine
from app.core.security.origen import resolver_origen_front
from app.integrations.workos_client import (
    get_cookie_password,
    get_frontend_url,
    get_workos,
)

logger = logging.getLogger(__name__)

# Roles del sistema. En WorkOS son roles de organización con slug "org-" + el rol en
# minúsculas y con guiones: org-cajero -> CAJERO, org-aprobador-credito ->
# APROBADOR_CREDITO (también se leen sin el prefijo "org-").
# Única fuente: los schemas (AUT-05..09) usan `Rol` y la autorización `ROLES`.
Rol = Literal[
    "ADMIN",
    "ASESOR",
    "CAJERO",
    "SUPERVISOR",
    "APROBADOR_CREDITO",
    "CONTADOR",
    "AUDITOR",
]
ROLES: tuple[Rol, ...] = get_args(Rol)

# __Host-: el navegador exige Secure y Path=/ y no permite Domain, así un subdominio
# no puede plantar ni pisar la cookie.
_PREFIJO_ROL = "ORG_"

COOKIE_SESION = "__Host-session"
DURACION_SESION = 8 * 60 * 60  # AUT-01: 8 h. Igualar a la sesión configurada en WorkOS

_METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}
_SITIOS_PROPIOS = {"same-origin", "none"}
# Peticiones paralelas con el token vencido comparten una sola renovación: WorkOS
# acepta cada refresh token una sola vez
_VIGENCIA_RENOVACION = 30.0
_renovaciones: dict[str, tuple[float, RefreshWithSessionCookieSuccessResponse]] = {}
_candado_renovacion = threading.Lock()

# Solo documenta la cookie en /api/docs; el valor se lee igual que con request.cookies
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
    # Valores fijos (pruebas). En una sesión real van en None y se leen con agencia()
    # e interno(), que consultan los vínculos guardados en la base.
    id_agencia: str | None = None
    id_interno: int | None = None
    # Consultas a la base: solo si la ruta necesita el dato y una vez por petición;
    # no se guardan entre peticiones.
    cargar_agencia: Callable[[], str | None] | None = field(
        default=None, repr=False, compare=False
    )
    cargar_interno: Callable[[], int | None] | None = field(
        default=None, repr=False, compare=False
    )
    _leidos: dict[str, str | int | None] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def roles_texto(self) -> str | None:
        """Roles que dio WorkOS, para Organizacion.Usuarios y Auditoria (RolesWorkOS)."""
        return ",".join(self.roles) or None

    def agencia(self) -> str | None:
        """IdAgencia del usuario (Organizacion.Usuarios.AgenciaID)."""
        if self.cargar_agencia is None:
            return self.id_agencia
        if "agencia" not in self._leidos:
            self._leidos["agencia"] = self.cargar_agencia()
        valor = self._leidos["agencia"]
        return valor if isinstance(valor, str) else None

    def interno(self, solo_si_leido: bool = False) -> int | None:
        """UsuarioID (Organizacion.Usuarios) cuya KeyUsuario es el id de WorkOS: se
        guarda en CreadoPor, RealizadoPor, etc.
        solo_si_leido: no consulta la base (auditoría de accesos denegados).
        """
        if self.cargar_interno is None:
            return self.id_interno
        if "interno" not in self._leidos:
            if solo_si_leido:
                return None
            self._leidos["interno"] = self.cargar_interno()
        valor = self._leidos["interno"]
        return valor if isinstance(valor, int) else None


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
    de FRONTEND_URL (o, en backend-dev, de la preview que resolvió el Worker) se
    rechaza con 403. Sin Origin ni Sec-Fetch-Site no es un navegador (Postman, curl),
    y ahí no hay CSRF posible.
    """
    if request.method in _METODOS_SEGUROS:
        return
    origen = request.headers.get("origin")
    sitio = request.headers.get("sec-fetch-site")
    if origen is None and (sitio is None or sitio in _SITIOS_PROPIOS):
        return
    if origen == get_frontend_url():
        return
    # Solo backend-dev: el origen de la preview que resolvió el Worker
    if (
        origen is not None
        and get_settings().frontend_origin_regex
        and origen == resolver_origen_front(request)
    ):
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
        nombre = crudo.strip().upper().replace("-", "_").removeprefix(_PREFIJO_ROL)
        if nombre in ROLES and nombre not in resultado:
            resultado.append(nombre)
    return tuple(resultado)


def slug_rol(rol: str) -> str:
    """Slug del rol en WorkOS: CAJERO -> org-cajero."""
    if rol not in ROLES:
        raise ValueError(f"Rol no válido: {rol}")
    return "org-" + rol.lower().replace("_", "-")


def _vinculo(base: DbName, consulta: str, llave: str) -> Any:
    """Busca el id interno vinculado a un id de WorkOS. None si no hay vínculo o la
    base falla: las rutas que lo necesitan responden 403 (fallan cerradas).
    """
    try:
        with get_engine(base).connect() as conn:
            return conn.execute(text(consulta), {"llave": llave}).scalar()
    except SQLAlchemyError as exc:
        logger.warning(
            "auth: no se pudo leer el vínculo base=%s error=%s",
            base,
            type(exc).__name__,
        )
        return None


def _id_interno_db(id_workos: str, roles: str | None) -> int | None:
    """Organizacion.Usuarios.KeyUsuario = id del usuario en WorkOS; solo activos.

    Guarda en RolesWorkOS los roles que dio WorkOS (solo si cambiaron): es la copia
    que usan AUT-05..09 y caja. None si no hay vínculo o la base falla (403).
    """
    try:
        with get_engine("seguridad").begin() as conn:
            fila = conn.execute(
                text(
                    "SELECT UsuarioID, RolesWorkOS FROM Organizacion.Usuarios "
                    "WHERE KeyUsuario = :llave AND Estado = 'Activo'"
                ),
                {"llave": id_workos},
            ).first()
            if fila is None:
                return None
            if fila.RolesWorkOS != roles:
                conn.execute(
                    text(
                        "UPDATE Organizacion.Usuarios SET RolesWorkOS = :roles "
                        "WHERE UsuarioID = :id"
                    ),
                    {"roles": roles, "id": fila.UsuarioID},
                )
            return fila.UsuarioID if isinstance(fila.UsuarioID, int) else None
    except SQLAlchemyError as exc:
        logger.warning(
            "auth: no se pudo leer el vínculo base=seguridad error=%s",
            type(exc).__name__,
        )
        return None


def codigo_agencia(agencia_id: object) -> str | None:
    """Organizacion.Usuarios.AgenciaID es int; Organizacion.Agencia.IdAgencia es
    char(3): 1 -> "001".
    """
    if isinstance(agencia_id, int) and 0 < agencia_id < 1000:
        return f"{agencia_id:03d}"
    return None


def _agencia_db(id_workos: str) -> str | None:
    """Agencia del usuario: Organizacion.Usuarios.AgenciaID del usuario Activo cuya
    KeyUsuario es el id de WorkOS.
    """
    return codigo_agencia(
        _vinculo(
            "seguridad",
            "SELECT AgenciaID FROM Organizacion.Usuarios "
            "WHERE KeyUsuario = :llave AND Estado = 'Activo'",
            id_workos,
        )
    )


def _roles_de_la_sesion(sesion: Exito) -> tuple[str, ...]:
    """Roles solo si la sesión es de la organización de la cooperativa (EnquoCoop).

    Una sesión de otra organización del mismo entorno de WorkOS no da roles: falla
    cerrado. Sin WORKOS_ORGANIZATION_ID configurado no se compara.
    """
    organizacion = get_settings().workos_organization_id
    if organizacion and sesion.organization_id != organizacion:
        logger.warning(
            "auth: sesión de otra organización usuario=%s organizacion=%s",
            sesion.user.id,
            sesion.organization_id,
        )
        return ()
    return normalizar_roles(sesion.roles, sesion.role)


def _usuario(sesion: Exito) -> Usuario:
    datos = sesion.user
    nombre = " ".join(p for p in (datos.first_name, datos.last_name) if p)
    roles = _roles_de_la_sesion(sesion)
    return Usuario(
        id_usuario=datos.id,
        id_sesion=sesion.session_id,
        id_organizacion=sesion.organization_id,
        nombre=nombre or datos.email,
        email=datos.email,
        roles=roles,
        permisos=tuple(sesion.permissions or ()),
        cargar_agencia=lambda: _agencia_db(datos.id),
        cargar_interno=lambda: _id_interno_db(datos.id, ",".join(roles) or None),
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
    # Para que la auditoría de un 403 posterior sepa quién lo intentó
    request.state.usuario = valida.usuario
    return valida.usuario


# Para recibir el usuario en un endpoint: def ver(usuario: UsuarioActual)
UsuarioActual = Annotated[Usuario, Depends(usuario_actual)]


def id_usuario_auditoria(usuario: UsuarioActual) -> int:
    """UsuarioID para CreadoPor/RealizadoPor: Organizacion.Usuarios.KeyUsuario."""
    id_interno = usuario.interno()
    if id_interno is None:
        raise problema(
            403,
            "USUARIO_SIN_VINCULO_AUDITORIA",
            "El usuario no tiene un vínculo de auditoría configurado.",
        )
    return id_interno


UsuarioAuditoria = Annotated[int, Depends(id_usuario_auditoria)]


def require_auth(usuario: UsuarioActual) -> Usuario:
    """Dependencia que declaran todos los routers: 401 sin sesión válida y 403 si el
    usuario de WorkOS no está registrado (KeyUsuario) o no está Activo en la base. Se
    resuelve antes que la ruta: nada se consulta ni se modifica sin ese registro.
    """
    if usuario.interno() is None:
        raise problema(
            403,
            "USUARIO_NO_REGISTRADO",
            "Su usuario no está registrado o no está activo.",
        )
    return usuario


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

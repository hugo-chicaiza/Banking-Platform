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

Duración e inactividad las impone WorkOS (8 h y 15 min); la cookie no tiene Max-Age.
Revocar en WorkOS no invalida el access token ya emitido (dura hasta 5 min), así que
los sid revocados desde la plataforma se guardan en una caché en memoria
(`revocar_sesion_local`) y se rechazan al instante. Cada 401 de sesión lleva el motivo
en `code` (`MotivoSesion`) para que el FE lo explique.

Cada 401/403 de la API queda en Auditoria.Auditoria (`AccesoDenegadoMiddleware`).
"""

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, cast, get_args

import jwt
from cryptography.fernet import Fernet, InvalidToken
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
from app.core.security.permisos import PERMISOS
from app.integrations.workos_client import (
    get_cookie_password,
    get_frontend_url,
    get_workos,
)

logger = logging.getLogger(__name__)

# Roles del sistema. En WorkOS son roles de organización con slug "org-" + el rol en
# minúsculas y con guiones: org-cajero -> CAJERO, org-aprobador-credito ->
# APROBADOR_CREDITO. Sin el prefijo no cuentan: "admin" y "member" son roles propios de
# WorkOS y no dan acceso a la plataforma.
# Única fuente: los schemas (AUT-05..09) usan `Rol` y la autorización `ROLES`.
Rol = Literal[
    "ADMIN",
    "ASESOR",
    "CAJERO",
    "SUPERVISOR",
    "APROBADOR_CREDITO",
    "CONTADOR",
    "AUDITOR",
    "CUMPLIMIENTO",
]
ROLES: tuple[Rol, ...] = get_args(Rol)

# __Host-: el navegador exige Secure y Path=/ y no permite Domain, así un subdominio
# no puede plantar ni pisar la cookie.
_PREFIJO_ROL = "org-"

COOKIE_SESION = "__Host-session"
# Igualar a la configuración de sesiones de WorkOS, que es la que las impone. Aquí solo
# sirven para explicar el 401 y para el TTL de la caché de sesiones revocadas.
DURACION_SESION = 8 * 60 * 60  # AUT-01: Maximum session length
INACTIVIDAD_SESION = 15 * 60  # Inactivity timeout (PCI DSS 8.2.8)
DURACION_ACCESS_TOKEN = 5 * 60  # Access token duration

# Motivo de un 401 de sesión (`code` del cuerpo). NO_AUTENTICADO: no hay cookie o no
# se puede leer.
MotivoSesion = Literal[
    "NO_AUTENTICADO",
    "SESION_EXPIRADA",
    "SESION_INACTIVA",
    "SESION_REVOCADA",
]
_MENSAJES_SESION: dict[MotivoSesion, str] = {
    "NO_AUTENTICADO": "Inicie sesión para continuar.",
    "SESION_EXPIRADA": "Su sesión alcanzó la duración máxima. Inicie sesión de nuevo.",
    "SESION_INACTIVA": "Su sesión se cerró por inactividad. Inicie sesión de nuevo.",
    "SESION_REVOCADA": (
        "Su sesión fue cerrada por un administrador. Inicie sesión de nuevo."
    ),
}

_METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}
_SITIOS_PROPIOS = {"same-origin", "none"}
# Peticiones paralelas con el token vencido comparten una sola renovación: WorkOS
# acepta cada refresh token una sola vez
_VIGENCIA_RENOVACION = 30.0
_renovaciones: dict[str, tuple[float, RefreshWithSessionCookieSuccessResponse]] = {}
_candado_renovacion = threading.Lock()

# Sesiones revocadas desde la plataforma: sid -> (vence, motivo). Basta con que dure
# lo que el access token (luego WorkOS rechaza la renovación); se guarda hasta la
# inactividad para que el 401 siga diciendo "revocada" y no "inactiva" o "expirada".
# Es por proceso: el backend corre en un solo proceso (python -m app).
_TTL_REVOCADA = max(DURACION_ACCESS_TOKEN, INACTIVIDAD_SESION) + 60
_revocadas: dict[str, tuple[float, MotivoSesion]] = {}
_candado_revocadas = threading.Lock()

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

    cargar_agencias: Callable[[], tuple[str, ...]] | None = field(
        default=None, repr=False, compare=False
    )
    id_agencias: tuple[str, ...] | None = None

    def agencias_permitidas(self) -> tuple[str, ...]:
        if self.cargar_agencias is not None:
            return self.cargar_agencias()
        if self.id_agencias is not None:
            return self.id_agencias
        return (self.id_agencia,) if self.id_agencia else ()

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
    # POST desde otros sitios. Sin Max-Age (cookie de sesión del navegador): si se
    # renovara en cada refresh alargaría la sesión; el límite lo imponen WorkOS (8 h y
    # 15 min de inactividad) y cerrar el navegador.
    response.set_cookie(
        COOKIE_SESION,
        sellada,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def borrar_cookie_sesion(response: Response) -> None:
    response.delete_cookie(
        COOKIE_SESION, path="/", secure=True, httponly=True, samesite="lax"
    )


def no_autenticado(
    borrar_cookie: bool = False, motivo: MotivoSesion = "NO_AUTENTICADO"
) -> HTTPException:
    headers: dict[str, str] = {}
    if borrar_cookie:
        # La respuesta de error es otra, así que el Set-Cookie va en la excepción
        temporal = Response()
        borrar_cookie_sesion(temporal)
        headers["Set-Cookie"] = temporal.headers["set-cookie"]
    return HTTPException(
        status_code=401,
        detail={"code": motivo, "message": _MENSAJES_SESION[motivo]},
        headers=headers or None,
    )


# --- Sesiones revocadas ----------------------------------------------------------


def revocar_sesion_local(
    id_sesion: str, motivo: MotivoSesion = "SESION_REVOCADA"
) -> None:
    """Rechaza el sid desde ya, sin esperar a que venza su access token. Llamarla
    después de revocar la sesión en WorkOS.
    """
    with _candado_revocadas:
        ahora = time.monotonic()
        for vieja in [k for k, (v, _) in _revocadas.items() if v <= ahora]:
            del _revocadas[vieja]
        _revocadas[id_sesion] = (ahora + _TTL_REVOCADA, motivo)


def motivo_revocacion(id_sesion: str) -> MotivoSesion | None:
    """Motivo si el sid está en la caché de revocadas; None si no."""
    with _candado_revocadas:
        entrada = _revocadas.get(id_sesion)
        if entrada is None:
            return None
        if entrada[0] <= time.monotonic():
            del _revocadas[id_sesion]
            return None
        return entrada[1]


def _datos_del_token(sellada: str) -> tuple[str | None, float | None] | None:
    """sid e iat del access token guardado en la cookie, sin validar la firma. Solo
    sirven para explicar un 401, nunca para dar acceso: la cookie está cifrada y
    autenticada con WORKOS_COOKIE_PASSWORD. None si no se puede leer.
    """
    try:
        datos = json.loads(Fernet(get_cookie_password()).decrypt(sellada.encode()))
        claims = jwt.decode(datos["access_token"], options={"verify_signature": False})
    except (InvalidToken, ValueError, KeyError, TypeError, jwt.PyJWTError):
        return None
    sid = claims.get("sid")
    iat = claims.get("iat")
    return (
        sid if isinstance(sid, str) else None,
        float(iat) if isinstance(iat, int | float) else None,
    )


def sid_de_cookie(sellada: str | None) -> str | None:
    """sid de la sesión guardada en la cookie, aunque ya no sirva (login desde el mismo
    navegador). Nadie puede fabricar una cookie con otro sid sin
    WORKOS_COOKIE_PASSWORD.
    """
    datos = _datos_del_token(sellada) if sellada else None
    return datos[0] if datos else None


def motivo_rechazo(sellada: str | None) -> MotivoSesion:
    """Por qué la sesión de la cookie ya no sirve.

    WorkOS responde igual (invalid_grant) a una sesión vencida, inactiva o revocada, así
    que se deduce: revocada si el sid está en la caché; inactiva si su último access
    token se emitió (última renovación) hace más que el tiempo de inactividad; si no,
    alcanzó la duración máxima.
    """
    datos = _datos_del_token(sellada) if sellada else None
    if datos is None:
        return "NO_AUTENTICADO"
    sid, emitido = datos
    revocada = motivo_revocacion(sid) if sid else None
    if revocada is not None:
        return revocada
    if emitido is not None and time.time() - emitido >= INACTIVIDAD_SESION:
        return "SESION_INACTIVA"
    return "SESION_EXPIRADA"


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
    """Lee `roles` o, si no viene, `role`. Acepta el slug de WorkOS (org-cajero) o el
    nombre del sistema tal como se guarda en RolesWorkOS (CAJERO). Ignora el resto,
    incluidos "admin" y "member", los roles propios de WorkOS: WorkOS exige slugs en
    minúsculas, así que nunca llega un nombre del sistema desde allí.
    """
    crudos = list(roles) if roles else [rol]
    resultado: list[str] = []
    for crudo in crudos:
        if not isinstance(crudo, str):
            continue
        crudo = crudo.strip()
        if crudo.startswith(_PREFIJO_ROL):
            nombre = crudo.removeprefix(_PREFIJO_ROL).upper().replace("-", "_")
        else:
            nombre = crudo
        if nombre in ROLES and nombre not in resultado:
            resultado.append(nombre)
    return tuple(resultado)


def slug_rol(rol: str) -> str:
    """Slug del rol en WorkOS: CAJERO -> org-cajero."""
    if rol not in ROLES:
        raise ValueError(f"Rol no válido: {rol}")
    return _PREFIJO_ROL + rol.lower().replace("_", "-")


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
            settings = get_settings()
            if (
                settings.e104_permiso_aprobar_roles.strip()
                or settings.e104_recuperar_correo
            ):
                from app.modules.auth.repository import (
                    cambio_roles_en_recuperacion,
                    sincronizacion_pendiente,
                )

                if (
                    settings.e104_permiso_aprobar_roles.strip()
                    and cambio_roles_en_recuperacion(
                        conn, fila.UsuarioID, settings.workos_organization_id
                    )
                ) or (
                    settings.e104_recuperar_correo
                    and sincronizacion_pendiente(conn, fila.UsuarioID, "Roles")
                ):
                    roles_sql = set((fila.RolesWorkOS or "").split(","))
                    roles_sesion = set((roles or "").split(","))
                    return fila.UsuarioID if roles_sesion == roles_sql else None
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


def _agencia_operativa_db(llave: str, sid: str, roles: tuple[str, ...]) -> str | None:
    from app.modules.auth.agencias import resolver_sesion

    return resolver_sesion(llave, sid, roles)


def _agencias_permitidas_db(llave: str, roles: tuple[str, ...]) -> tuple[str, ...]:
    from app.modules.auth.agencias import alcance_sesion

    return alcance_sesion(llave, roles)


def _roles_de_la_sesion(sesion: Exito) -> tuple[str, ...]:
    """Roles solo si la sesión es de la organización de la cooperativa (EnquoCoop).

    Una sesión de otra organización del mismo entorno de WorkOS no da roles: falla
    cerrado. Sin WORKOS_ORGANIZATION_ID configurado no se compara.
    """
    organizacion = get_settings().workos_organization_id
    if organizacion and sesion.organization_id != organizacion:
        logger.warning("auth: sesion de organizacion no autorizada")
        return ()
    return normalizar_roles(sesion.roles, sesion.role)


def _usuario(sesion: Exito) -> Usuario:
    datos = sesion.user
    nombre = " ".join(p for p in (datos.first_name, datos.last_name) if p)
    organizacion = get_settings().workos_organization_id
    if organizacion and sesion.organization_id != organizacion:
        logger.warning("auth: sesion de organizacion no autorizada")
        raise problema(
            403,
            "ORGANIZACION_NO_AUTORIZADA",
            "La sesion no pertenece a la organizacion autorizada.",
        )
    roles = _roles_de_la_sesion(sesion)
    return Usuario(
        id_usuario=datos.id,
        id_sesion=sesion.session_id,
        id_organizacion=sesion.organization_id,
        nombre=nombre or datos.email,
        email=datos.email,
        roles=roles,
        permisos=tuple(sesion.permissions or ()),
        cargar_agencia=lambda: _agencia_operativa_db(
            datos.id, sesion.session_id, roles
        ),
        cargar_agencias=lambda: _agencias_permitidas_db(datos.id, roles),
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


def _no_revocada(valida: SesionValida) -> SesionValida | None:
    if motivo_revocacion(valida.usuario.id_sesion) is not None:
        logger.info(
            "auth: sesión revocada rechazada usuario=%s", valida.usuario.id_usuario
        )
        return None
    return valida


def renovar_sesion(sellada: str) -> SesionValida | None:
    """Pide a WorkOS un access token nuevo. None si la sesión ya no sirve."""
    resultado = _renovar(sellada)
    if not isinstance(resultado, RefreshWithSessionCookieSuccessResponse):
        return None
    return _no_revocada(SesionValida(_usuario(resultado), resultado.sealed_session))


def validar_sesion(sellada: str) -> SesionValida | None:
    """Descifra la cookie y valida el access token; si venció, lo renueva.

    None si la cookie no sirve o la sesión está revocada (el motivo lo da
    `motivo_rechazo`); 503 si no se pueden descargar las llaves de WorkOS.
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
    return _no_revocada(SesionValida(_usuario(resultado), None))


# --- Dependencias ----------------------------------------------------------------


def _contexto_pagina_vigente(usuario: Usuario, valor: str) -> bool:
    if valor == "global":
        from app.modules.auth.agencias import contexto_usuario

        return contexto_usuario(usuario).alcance_global
    return (
        len(valor) == 3
        and valor.isascii()
        and valor.isdigit()
        and valor == usuario.agencia()
    )


def usuario_actual(
    request: Request,
    response: Response,
    sellada: Annotated[str | None, Depends(_cookie)],
) -> Usuario:
    """401 sin sesión válida, con el motivo en `code` (MotivoSesion); 403 si un
    POST/PUT/PATCH/DELETE viene de otro origen.
    """
    verificar_origen(request)
    if not sellada:
        raise no_autenticado()
    valida = validar_sesion(sellada)
    if valida is None:
        raise no_autenticado(borrar_cookie=True, motivo=motivo_rechazo(sellada))
    if valida.sellada_nueva:
        guardar_cookie_sesion(response, valida.sellada_nueva)
    agencia_pagina = request.headers.get("X-Agencia-Contexto")
    excepciones = {
        "/api/v1/auth/agencia-activa",
        "/api/v1/auth/logout",
        "/api/v1/auth/refresh",
    }
    if (
        request.method not in _METODOS_SEGUROS
        and agencia_pagina is not None
        and request.url.path not in excepciones
    ) and (not _contexto_pagina_vigente(valida.usuario, agencia_pagina)):
        request.state.usuario = valida.usuario
        raise problema(
            409,
            "CONTEXTO_AGENCIA_DESACTUALIZADO",
            "La agencia operativa cambio. Recarga la pantalla antes de continuar.",
        )
    # Para que la auditoría de un 403 posterior sepa quién lo intentó
    request.state.usuario = valida.usuario
    return valida.usuario


# Para recibir el usuario en un endpoint: def ver(usuario: UsuarioActual)
UsuarioActual = Annotated[Usuario, Depends(usuario_actual)]
_SIN_PETICION = cast(Request, None)


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


def require_auth(request: Request, usuario: UsuarioActual) -> Usuario:
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
    from app.modules.seguridad import funciones

    if funciones.activa():
        funciones.verificar_peticion(request, usuario)
    else:
        from app.core.security.secciones import verificar_seccion

        verificar_seccion(request, usuario)
    return usuario


def require_roles(*permitidos: str) -> Callable[..., Usuario]:
    """Rol anterior o función SQL para una operación explícitamente migrada.

    No amplía autorizaciones en rutas ajenas al catálogo ni con el modelo apagado.
    """
    desconocidos = set(permitidos) - set(ROLES)
    if not permitidos or desconocidos:
        raise ValueError(f"Roles no válidos: {sorted(desconocidos)}")

    # FastAPI inyecta Request. Sin petición, conserva las llamadas internas previas.
    def verificar(usuario: UsuarioActual, request: Request = _SIN_PETICION) -> Usuario:
        from app.modules.seguridad import funciones

        if request is not None and funciones.autorizar_operacion(request, usuario):
            return usuario
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


def require_permiso(*permitidos: str) -> Callable[..., Usuario]:
    """Permiso WorkOS anterior o función SQL en una operación migrada.

    La sustitución es por método/ruta, nunca una concesión global del permiso remoto.
    """
    desconocidos = set(permitidos) - set(PERMISOS)
    if not permitidos or desconocidos:
        raise ValueError(f"Permisos no válidos: {sorted(desconocidos)}")

    def verificar(usuario: UsuarioActual, request: Request = _SIN_PETICION) -> Usuario:
        from app.modules.seguridad import funciones

        if request is not None and funciones.autorizar_operacion(request, usuario):
            return usuario
        if not set(usuario.permisos) & set(permitidos):
            logger.warning(
                "auth: acceso denegado usuario=%s permisos=%s requeridos=%s",
                usuario.id_usuario,
                ",".join(usuario.permisos),
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

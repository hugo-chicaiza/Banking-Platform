"""Reglas de AUT-01..04 (sesión, patrón BFF) y AUT-05..09 (usuarios internos, C-05).

WorkOS guarda credenciales, sesiones y el rol (membresía en EnquoCoop). La base guarda
el usuario interno (Organizacion.Usuarios), su estado, agencia y bloqueos. Nunca se
registran tokens, codes, cookies ni datos personales en logs.
"""

import base64
import binascii
import hashlib
import logging
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import Connection
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from workos.exceptions import (
    AuthenticationException,
    BaseRequestException,
    ServerException,
)
from workos.types.user_management import Invitation, OrganizationMembership, User

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.core.security import audit
from app.core.security.auth import (
    SesionValida,
    Usuario,
    codigo_agencia,
    normalizar_roles,
    renovar_sesion,
    slug_rol,
    validar_sesion,
)
from app.core.security.operador import auditar
from app.integrations.workos_client import (
    get_cookie_password,
    get_frontend_url,
    get_organizacion_id,
    get_redirect_uri,
    get_workos,
)
from app.modules.auth import repository
from app.modules.auth.schemas import (
    BloqueoVigente,
    EstadoInvitacion,
    PageUsuario,
    RolUpdate,
    UsuarioCreate,
    UsuarioDetalle,
    UsuarioResumen,
    UsuarioSesion,
    UsuarioUpdate,
)

logger = logging.getLogger(__name__)

# Ruta interna del FE: empieza con "/"
_RUTA_INTERNA = re.compile(r"^/(?![/\\])[!-\[\]-~]{0,511}$")
_VERIFICADOR_PKCE = re.compile(r"[A-Za-z0-9_-]{43}")
_RUTA_POR_DEFECTO = "/"
_RUTA_LOGIN = "/login"
_TABLA_AUDITORIA = "WorkOS.Sesiones"
# Códigos de error de WorkOS (user_already_organization_member): se publican tal cual
_CODIGO_WORKOS = re.compile(r"[a-z0-9_]{1,64}")


def ruta_segura(return_to: str | None) -> str:
    """return_to solo puede ser una ruta del FE; si no, se usa "/"."""
    if return_to and _RUTA_INTERNA.fullmatch(return_to):
        return return_to
    return _RUTA_POR_DEFECTO


def _url_error(code: str, origen: str) -> str:
    return f"{origen}{_RUTA_LOGIN}?error={code}"


def _redirect_uri(origen: str) -> str:
    """WORKOS_REDIRECT_URI; desde una preview (backend-dev), la misma ruta en el origen
    de la preview: así la cookie de state vuelve al host que la creó.
    """
    configurada = get_redirect_uri()
    if origen == get_frontend_url():
        return configurada
    return f"{origen}{urlsplit(configurada).path}"


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


def _vincular(
    id_workos: str, email: str, email_verificado: bool, ip: str | None
) -> None:
    """Primer login de un usuario creado con AUT-06: guarda su KeyUsuario (mismo
    email, verificado por WorkOS al aceptar la invitación) y su último acceso.

    Si la base falla el login sigue: las rutas protegidas responderán 403 hasta que
    el vínculo exista (fallan cerradas).
    """
    try:
        with get_engine("seguridad").begin() as conn:
            vinculado = email_verificado and repository.vincular(
                conn, id_workos, email.lower()
            )
            repository.registrar_acceso(conn, id_workos)
    except SQLAlchemyError as exc:
        logger.warning("auth: no se pudo vincular error=%s", type(exc).__name__)
        return
    if vinculado:
        _auditar("VINCULAR", "Exitoso", f"AUT-01 Vínculo workos_user={id_workos}", ip)


def _no_habilitado(sellada: str) -> str | None:
    """Código de error si la sesión recién creada no puede entrar; None si puede.

    Solo entra un usuario interno vinculado y Activo (Bloqueado o Inactivo no), con
    sesión de EnquoCoop: WorkOS no tiene bloqueo de usuario y con la membresía inactiva
    igual entrega una sesión, sin organización. Si no puede entrar, la sesión se revoca
    en WorkOS para que no quede viva.
    """
    try:
        sesion = validar_sesion(sellada)
    except HTTPException:
        # No se pudieron descargar las llaves de WorkOS
        return "AUTENTICACION_NO_DISPONIBLE"
    if sesion is None:
        return "CREDENCIALES_INVALIDAS"
    usuario = sesion.usuario
    organizacion = get_settings().workos_organization_id
    if (
        not organizacion or usuario.id_organizacion == organizacion
    ) and usuario.interno() is not None:
        return None
    try:
        get_workos().user_management.revoke_session(session_id=usuario.id_sesion)
    except Exception as exc:  # noqa: BLE001 - la cookie no se crea igual
        logger.warning("auth: no se pudo revocar la sesión tipo=%s", type(exc).__name__)
    return "USUARIO_NO_HABILITADO"


def iniciar_login(return_to: str | None, origen: str) -> tuple[str, str]:
    """Devuelve la URL del Hosted UI y el valor de la cookie de state.

    La cookie guarda el state, el verificador PKCE y la ruta de regreso. `origen` es
    el del FE (resolver_origen_front): define a qué callback vuelve AuthKit.
    """
    state = secrets.token_urlsafe(32)
    verificador = secrets.token_urlsafe(32)
    resumen = hashlib.sha256(verificador.encode("ascii")).digest()
    desafio = base64.urlsafe_b64encode(resumen).decode("ascii").rstrip("=")
    # Sin el relleno "=": así el valor de la cookie no necesita comillas
    ruta = ruta_segura(return_to).encode()
    destino = base64.urlsafe_b64encode(ruta).decode().rstrip("=")
    url = get_workos().user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=_redirect_uri(origen),
        state=state,
        code_challenge=desafio,
    )
    return url, f"{state}.{verificador}.{destino}"


def _leer_cookie_state(valor: str | None) -> tuple[str, str, str] | None:
    partes = (valor or "").split(".", 2)
    if len(partes) != 3:
        return None
    state, verificador, destino = partes
    if not _VERIFICADOR_PKCE.fullmatch(verificador):
        return None
    try:
        relleno = "=" * (-len(destino) % 4)
        ruta = base64.urlsafe_b64decode((destino + relleno).encode()).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    return state, verificador, ruta_segura(ruta)


def completar_login(
    code: str | None,
    state: str | None,
    error: str | None,
    cookie_state: str | None,
    ip: str | None,
    user_agent: str | None,
    origen: str,
) -> tuple[str, str | None]:
    """Canjea el code. Devuelve a dónde redirigir (en `origen`, el del FE) y la sesión
    sellada (None si falló).
    """
    guardado = _leer_cookie_state(cookie_state)

    def fallo(code_error: str, motivo: str) -> tuple[str, None]:
        logger.warning("auth: login fallido motivo=%s", motivo)
        _auditar("LOGIN", "Fallido", f"AUT-01 Inicio de sesión {code_error}", ip)
        return _url_error(code_error, origen), None

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

    _, verificador, ruta = guardado
    try:
        resultado = get_workos().user_management.authenticate_with_code(
            code=code,
            code_verifier=verificador,
            session={"seal_session": True, "cookie_password": get_cookie_password()},
            ip_address=ip,
            user_agent=user_agent,
        )
    except (ServerException, httpx.HTTPError) as exc:
        logger.error("auth: WorkOS no disponible tipo=%s", type(exc).__name__)
        return _url_error("AUTENTICACION_NO_DISPONIBLE", origen), None
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
    _vincular(
        resultado.user.id, resultado.user.email, resultado.user.email_verified, ip
    )
    codigo = _no_habilitado(resultado.sealed_session)
    if codigo is not None:
        logger.info("auth: login rechazado usuario=%s", resultado.user.id)
        return fallo(codigo, "no_habilitado")
    _auditar(
        "LOGIN",
        "Exitoso",
        f"AUT-01 Inicio de sesión workos_user={resultado.user.id}",
        ip,
    )
    logger.info("auth: login usuario=%s", resultado.user.id)
    return f"{origen}{ruta}", resultado.sealed_session


# --- AUT-02 refresh ----------------------------------------------------------------


def refrescar(sellada: str | None) -> SesionValida | None:
    """Renueva el access token aunque no haya vencido. None si la sesión no sirve."""
    return renovar_sesion(sellada) if sellada else None


# --- AUT-03 logout -----------------------------------------------------------------


def cerrar_sesion(sellada: str | None, ip: str | None, origen: str) -> str:
    """URL a la que el FE debe navegar. Idempotente: sin sesión devuelve /login del
    `origen` (el del FE).
    """
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
        id_agencia=usuario.agencia(),
    )


# --- AUT-05..09 usuarios internos (C-05) -------------------------------------------
#
# La base es la fuente del usuario interno (datos, estado, agencia, bloqueos) y WorkOS
# la del rol (membresía en EnquoCoop), que se copia en RolesWorkOS. Las llamadas a
# WorkOS van dentro de la transacción: si fallan, la base se revierte (503). Lo que
# WorkOS ya aplicó se deshace en orden inverso (best effort, queda en el log).

_TABLA_USUARIOS = "Organizacion.Usuarios"
_ORDEN_POR_DEFECTO = "fechaCreacion,desc"
_ORDENES = frozenset(
    f"{campo},{direccion}"
    for campo in (
        "username",
        "nombres",
        "apellidos",
        "email",
        "estado",
        "fechaCreacion",
    )
    for direccion in ("asc", "desc")
)
_ESTADOS_INVITACION: frozenset[str] = frozenset(
    {"pending", "accepted", "expired", "revoked"}
)
_SLUG_ADMIN = slug_rol("ADMIN")

Deshacer = list[Callable[[], object]]


@contextmanager
def _workos(operacion: str) -> Iterator[None]:
    """Traduce los errores de WorkOS: caído o mal configurado → 503; rechazo → 422."""
    try:
        yield
    except (ServerException, AuthenticationException, httpx.HTTPError) as exc:
        logger.error(
            "usuarios: WorkOS no disponible operacion=%s tipo=%s",
            operacion,
            type(exc).__name__,
        )
        raise problema(
            503, "WORKOS_NO_DISPONIBLE", "El servicio de usuarios no está disponible."
        ) from None
    except BaseRequestException as exc:
        codigo = exc.code or exc.error
        logger.warning(
            "usuarios: WorkOS rechazó operacion=%s code=%s request_id=%s",
            operacion,
            codigo,
            exc.request_id,
        )
        mensaje = "WorkOS rechazó la operación solicitada."
        if isinstance(codigo, str) and _CODIGO_WORKOS.fullmatch(codigo):
            mensaje = f"WorkOS rechazó la operación solicitada ({codigo})."
        raise problema(422, "WORKOS_RECHAZO", mensaje) from None


def _deshacer(pasos: Deshacer) -> None:
    for paso in reversed(pasos):
        try:
            paso()
        except Exception as exc:  # noqa: BLE001 - best effort, se registra
            logger.error(
                "usuarios: no se pudo deshacer en WorkOS tipo=%s (revisar a mano)",
                type(exc).__name__,
            )


def _no_encontrado() -> HTTPException:
    return problema(404, "USUARIO_NO_ENCONTRADO", "El usuario no existe.")


def _duplicado() -> HTTPException:
    return problema(
        409,
        "USUARIO_DUPLICADO",
        "Ya existe un usuario con ese username, email o cédula.",
    )


def _rol(fila: repository.Fila) -> str | None:
    roles = normalizar_roles((fila["RolesWorkOS"] or "").split(","), None)
    return roles[0] if roles else None


def _resumen(fila: repository.Fila) -> UsuarioResumen:
    return UsuarioResumen(
        id_usuario=fila["UsuarioID"],
        username=fila["NombreUsuario"],
        nombres=fila["Nombres"],
        apellidos=fila["Apellidos"],
        email=fila["Email"],
        rol=_rol(fila),
        estado=fila["Estado"],
        id_agencia=codigo_agencia(fila["AgenciaID"]),
        vinculado=fila["KeyUsuario"] is not None,
        fecha_creacion=fila["FechaCreacion"],
    )


def _detalle(
    conn: Connection,
    fila: repository.Fila,
    estado_invitacion: EstadoInvitacion | None = None,
) -> UsuarioDetalle:
    bloqueo = None
    if fila["Estado"] == "Bloqueado":
        vigente = repository.bloqueo_vigente(conn, fila["UsuarioID"])
        if vigente is not None:
            bloqueo = BloqueoVigente(
                motivo=vigente["MotivoBloqueo"],
                fecha_bloqueo=vigente["FechaBloqueo"],
                observaciones=vigente["Observaciones"],
            )
    return UsuarioDetalle(
        **_resumen(fila).model_dump(),
        cedula=fila["Cedula"],
        ultimo_acceso=repository.fecha(fila["UltimoAcceso"]),
        estado_invitacion=estado_invitacion,
        bloqueo=bloqueo,
    )


def _cargar(
    conn: Connection, id_usuario: int, bloquear: bool = False
) -> repository.Fila:
    fila = repository.obtener_usuario(conn, id_usuario, bloquear=bloquear)
    if fila is None:
        raise _no_encontrado()
    return fila


def _validar_agencia(conn_coop: Connection, id_agencia: str) -> None:
    if not repository.agencia_activa(conn_coop, id_agencia):
        raise problema(
            422, "AGENCIA_INVALIDA", "La agencia no existe o no está activa."
        )


# --- WorkOS ------------------------------------------------------------------------


def _inviter(usuario: Usuario) -> str | None:
    # WorkOS exige que quien invita sea miembro de la organización
    if usuario.id_organizacion == get_organizacion_id():
        return usuario.id_usuario
    return None


def _invitar(email: str, rol: str, usuario: Usuario) -> Invitation:
    with _workos("send_invitation"):
        return get_workos().user_management.send_invitation(
            email=email,
            organization_id=get_organizacion_id(),
            role_slug=slug_rol(rol),
            inviter_user_id=_inviter(usuario),
        )


def _revocar_invitacion(id_invitacion: str) -> None:
    with _workos("revoke_invitation"):
        get_workos().user_management.revoke_invitation(id_invitacion)


def _invitacion_pendiente(email: str) -> Invitation | None:
    with _workos("list_invitations"):
        invitaciones = get_workos().user_management.list_invitations(
            email=email, organization_id=get_organizacion_id()
        )
        return next((i for i in invitaciones if i.state == "pending"), None)


def _membresia(id_workos: str) -> OrganizationMembership | None:
    with _workos("list_organization_memberships"):
        membresias = get_workos().user_management.list_organization_memberships(
            user_id=id_workos,
            organization_id=get_organizacion_id(),
            statuses=["active", "inactive"],
        )
        return next(iter(membresias), None)


def _usuario_workos(email: str) -> User | None:
    with _workos("list_users"):
        usuarios = get_workos().user_management.list_users(email=email, limit=1)
        return next(iter(usuarios), None)


def _resolver_sin_vinculo(conn: Connection, fila: repository.Fila) -> str | None:
    """Fila sin KeyUsuario: decide qué hay en WorkOS con ese email.

    - Ni usuario ni miembro: None, la invitación sigue pendiente (se revoca y reinvita).
    - Usuario de WorkOS sin membresía en EnquoCoop: 409, no se reinvita.
    - Miembro de EnquoCoop (aceptó, pero el login no lo vinculó): su id. Si WorkOS
      verificó su email se guarda como KeyUsuario, igual que en el primer login.
    """
    encontrado = _usuario_workos(fila["Email"])
    if encontrado is None:
        return None
    if _membresia(encontrado.id) is None:
        raise problema(
            409,
            "USUARIO_WORKOS_SIN_MEMBRESIA",
            "El email ya tiene usuario en WorkOS, pero no es miembro de la organización.",
        )
    if repository.vinculado_a_otro(conn, encontrado.id, fila["UsuarioID"]):
        logger.warning(
            "usuarios: workos_user=%s ya vinculado a otro usuario", encontrado.id
        )
        raise problema(
            409,
            "VINCULO_EN_CONFLICTO",
            "El usuario de WorkOS ya está vinculado a otro usuario interno.",
        )
    if encontrado.email_verified and repository.vincular_por_id(
        conn, fila["UsuarioID"], encontrado.id
    ):
        logger.info(
            "usuarios: vinculado id=%s workos_user=%s", fila["UsuarioID"], encontrado.id
        )
    return encontrado.id


def _slugs(membresia: OrganizationMembership) -> set[str]:
    roles = membresia.roles or [membresia.role]
    return {rol["slug"] for rol in roles}


def _revocar_sesiones(id_workos: str) -> None:
    """Un bloqueo no espera a que venza la sesión de 8 h."""
    with _workos("revoke_session"):
        gestion = get_workos().user_management
        for sesion in gestion.list_sessions(user_id=id_workos):
            if sesion.status == "active":
                gestion.revoke_session(session_id=sesion.id)


def _validar_ultimo_admin(conn: Connection, fila: repository.Fila) -> None:
    """Cuenta como ADMIN real: Activo, vinculado y con membresía activa org-admin."""
    if _rol(fila) != "ADMIN" or fila["Estado"] != "Activo" or not fila["KeyUsuario"]:
        return
    with _workos("list_organization_memberships"):
        ids = [
            m.user_id
            for m in get_workos().user_management.list_organization_memberships(
                organization_id=get_organizacion_id(), statuses=["active"]
            )
            if _SLUG_ADMIN in _slugs(m) and m.user_id != fila["KeyUsuario"]
        ]
    if repository.contar_activos_vinculados(conn, ids, fila["UsuarioID"]) == 0:
        raise problema(
            409, "ULTIMO_ADMIN", "No se puede quitar el último administrador activo."
        )


def _estado_invitacion(email: str) -> EstadoInvitacion | None:
    """Estado de la última invitación. Si WorkOS no responde, el detalle sale igual."""
    try:
        with _workos("list_invitations"):
            invitaciones = get_workos().user_management.list_invitations(
                email=email, organization_id=get_organizacion_id()
            )
            ultima = next(iter(invitaciones), None)
    except HTTPException:
        return None
    if ultima is None or ultima.state not in _ESTADOS_INVITACION:
        return None
    return ultima.state  # type: ignore[return-value]


# --- AUT-05 ------------------------------------------------------------------------


def listar_usuarios(
    conn: Connection,
    *,
    q: str | None,
    estado: str | None,
    id_agencia: str | None,
    rol: str | None,
    vinculado: bool | None,
    page: int,
    page_size: int,
    sort: str | None,
) -> PageUsuario:
    orden = sort or _ORDEN_POR_DEFECTO
    if orden not in _ORDENES:
        raise problema(400, "SORT_INVALIDO", "El ordenamiento solicitado no es válido.")
    filas, total = repository.listar_usuarios(
        conn,
        q=q.strip() if q else None,
        estado=estado,
        agencia_id=int(id_agencia) if id_agencia else None,
        rol=rol,
        vinculado=vinculado,
        orden=orden,
        page=page,
        page_size=page_size,
    )
    return PageUsuario(
        items=[_resumen(f) for f in filas], page=page, page_size=page_size, total=total
    )


# --- AUT-06 ------------------------------------------------------------------------


def crear_usuario(
    conn: Connection,
    conn_coop: Connection,
    datos: UsuarioCreate,
    usuario: Usuario,
    ip: str,
) -> UsuarioDetalle:
    """Inserta el usuario (sin KeyUsuario) e invita a EnquoCoop con su rol.

    WorkOS falla → se revierte (503). Falla el commit después de invitar → se revoca
    la invitación.
    """
    _validar_agencia(conn_coop, datos.id_agencia)
    with auditar(
        "CREAR", _TABLA_USUARIOS, usuario, ip, f"AUT-06 rol={datos.rol}"
    ) as registro:
        invitacion: Invitation | None = None
        try:
            with conn.begin():
                if repository.existe_duplicado(
                    conn,
                    username=datos.username,
                    email=datos.email,
                    cedula=datos.cedula,
                ):
                    raise _duplicado()
                id_nuevo = repository.insertar_usuario(
                    conn,
                    username=datos.username,
                    nombres=datos.nombres,
                    apellidos=datos.apellidos,
                    email=datos.email,
                    cedula=datos.cedula,
                    agencia_id=int(datos.id_agencia),
                    rol=datos.rol,
                )
                registro.id_registro = str(id_nuevo)
                invitacion = _invitar(datos.email, datos.rol, usuario)
        except SQLAlchemyError as exc:
            if invitacion is not None:
                id_invitacion = invitacion.id
                _deshacer([lambda: _revocar_invitacion(id_invitacion)])
            if isinstance(exc, IntegrityError):
                raise _duplicado() from None
            raise
        return _detalle(conn, _cargar(conn, id_nuevo), estado_invitacion="pending")


# --- AUT-07 ------------------------------------------------------------------------


def obtener_usuario(conn: Connection, id_usuario: int) -> UsuarioDetalle:
    fila = _cargar(conn, id_usuario)
    estado = None if fila["KeyUsuario"] else _estado_invitacion(fila["Email"])
    return _detalle(conn, fila, estado_invitacion=estado)


# --- AUT-08 ------------------------------------------------------------------------


def _sincronizar_vinculado(
    key: str,
    fila: repository.Fila,
    nuevo_estado: str | None,
    nuevo_email: str | None,
    cambios: UsuarioUpdate,
    deshacer: Deshacer,
) -> None:
    """Usuario de WorkOS miembro de EnquoCoop: se cambia el usuario y la membresía."""
    gestion = get_workos().user_management
    if nuevo_email or cambios.nombres or cambios.apellidos:
        with _workos("update_user"):
            gestion.update_user(
                user_id=key,
                email=nuevo_email,
                first_name=cambios.nombres,
                last_name=cambios.apellidos,
            )
        deshacer.append(
            lambda: gestion.update_user(
                user_id=key,
                email=fila["Email"],
                first_name=fila["Nombres"],
                last_name=fila["Apellidos"],
            )
        )
    if nuevo_estado is None:
        return
    membresia = _membresia(key)
    if membresia is None:
        return
    id_membresia = membresia.id
    if nuevo_estado == "Activo" and membresia.status != "active":
        with _workos("reactivate_organization_membership"):
            gestion.reactivate_organization_membership(id_membresia)
        deshacer.append(
            lambda: gestion.deactivate_organization_membership(id_membresia)
        )
    elif nuevo_estado != "Activo" and membresia.status == "active":
        with _workos("deactivate_organization_membership"):
            gestion.deactivate_organization_membership(id_membresia)
        deshacer.append(
            lambda: gestion.reactivate_organization_membership(id_membresia)
        )
        _revocar_sesiones(key)


def _sincronizar_pendiente(
    fila: repository.Fila,
    nuevo_estado: str | None,
    nuevo_email: str | None,
    usuario: Usuario,
    deshacer: Deshacer,
) -> None:
    """Sin usuario en WorkOS, lo único que hay es la invitación: se revoca y, si el
    usuario queda Activo, se envía otra (al email nuevo, si cambió).
    """
    if not nuevo_estado and not nuevo_email:
        return
    pendiente = _invitacion_pendiente(fila["Email"])
    if pendiente is not None:
        _revocar_invitacion(pendiente.id)
    rol = _rol(fila)
    if (nuevo_estado or fila["Estado"]) == "Activo" and rol is not None:
        nueva = _invitar(nuevo_email or fila["Email"], rol, usuario)
        id_nueva = nueva.id
        deshacer.append(lambda: _revocar_invitacion(id_nueva))


def _mover_cajero(
    conn_coop: Connection, id_usuario: int, id_agencia: str, id_admin: int
) -> None:
    with conn_coop.begin():
        repository.cerrar_asignacion(conn_coop, id_usuario)
        repository.abrir_asignacion(
            conn_coop,
            id_usuario,
            id_agencia,
            asignado_por=id_admin,
            motivo="AUT-08 cambio de agencia",
        )


def actualizar_usuario(
    conn: Connection,
    conn_coop: Connection,
    id_usuario: int,
    cambios: UsuarioUpdate,
    usuario: Usuario,
    id_admin: int,
    ip: str,
) -> UsuarioDetalle:
    campos = ",".join(sorted(cambios.model_dump(exclude_none=True)))
    with auditar(
        "ACTUALIZAR",
        _TABLA_USUARIOS,
        usuario,
        ip,
        f"AUT-08 campos={campos}",
        str(id_usuario),
    ):
        deshacer: Deshacer = []
        try:
            with conn.begin():
                fila = _cargar(conn, id_usuario, bloquear=True)
                nuevo_estado = (
                    cambios.estado if cambios.estado != fila["Estado"] else None
                )
                nuevo_email = (
                    cambios.email
                    if cambios.email and cambios.email != fila["Email"].lower()
                    else None
                )
                agencia = (
                    cambios.id_agencia
                    if cambios.id_agencia != codigo_agencia(fila["AgenciaID"])
                    else None
                )

                if nuevo_estado and nuevo_estado != "Activo":
                    if id_usuario == id_admin:
                        raise problema(
                            409,
                            "OPERACION_SOBRE_SI_MISMO",
                            "No puede bloquear ni desactivar su propio usuario.",
                        )
                    _validar_ultimo_admin(conn, fila)
                if nuevo_email and repository.existe_duplicado(
                    conn,
                    username=None,
                    email=nuevo_email,
                    cedula=None,
                    excluir_id=id_usuario,
                ):
                    raise _duplicado()
                if agencia:
                    _validar_agencia(conn_coop, agencia)
                key = fila["KeyUsuario"]
                if not key and (
                    nuevo_estado or nuevo_email or cambios.nombres or cambios.apellidos
                ):
                    key = _resolver_sin_vinculo(conn, fila)

                repository.actualizar_usuario(
                    conn,
                    id_usuario,
                    nombres=cambios.nombres,
                    apellidos=cambios.apellidos,
                    email=nuevo_email,
                    estado=nuevo_estado,
                    agencia_id=int(agencia) if agencia else None,
                )
                if nuevo_estado:
                    if fila["Estado"] == "Bloqueado":
                        repository.cerrar_bloqueos(conn, id_usuario, id_admin)
                    if nuevo_estado == "Bloqueado":
                        repository.abrir_bloqueo(
                            conn,
                            id_usuario,
                            motivo=cambios.motivo or "",
                            observaciones=cambios.observaciones,
                            bloqueado_por=id_admin,
                        )
                if key:
                    _sincronizar_vinculado(
                        key, fila, nuevo_estado, nuevo_email, cambios, deshacer
                    )
                else:
                    _sincronizar_pendiente(
                        fila, nuevo_estado, nuevo_email, usuario, deshacer
                    )
                # Otra base: va al final para no dejarla cambiada si algo antes falla
                if agencia and _rol(fila) == "CAJERO":
                    _mover_cajero(conn_coop, id_usuario, agencia, id_admin)
        except IntegrityError:
            _deshacer(deshacer)
            raise _duplicado() from None
        except Exception:
            _deshacer(deshacer)
            raise
        return _detalle(conn, _cargar(conn, id_usuario))


# --- AUT-09 ------------------------------------------------------------------------


def _aplicar_rol_en_workos(
    fila: repository.Fila,
    key: str | None,
    rol: str,
    usuario: Usuario,
    deshacer: Deshacer,
) -> None:
    gestion = get_workos().user_management
    if key:
        membresia = _membresia(key)
        if membresia is None:
            with _workos("create_organization_membership"):
                gestion.create_organization_membership(
                    user_id=key,
                    organization_id=get_organizacion_id(),
                    role_slug=slug_rol(rol),
                )
            return
        id_membresia = membresia.id
        anterior = membresia.role["slug"]
        with _workos("update_organization_membership"):
            gestion.update_organization_membership(
                organization_membership_id=id_membresia, role_slug=slug_rol(rol)
            )
        deshacer.append(
            lambda: gestion.update_organization_membership(
                organization_membership_id=id_membresia, role_slug=anterior
            )
        )
    elif fila["Estado"] == "Activo":
        # Sin usuario en WorkOS: la invitación lleva el rol, así que se reemplaza
        pendiente = _invitacion_pendiente(fila["Email"])
        if pendiente is not None:
            _revocar_invitacion(pendiente.id)
        nueva = _invitar(fila["Email"], rol, usuario)
        id_nueva = nueva.id
        deshacer.append(lambda: _revocar_invitacion(id_nueva))


def cambiar_rol(
    conn: Connection,
    conn_coop: Connection,
    id_usuario: int,
    datos: RolUpdate,
    usuario: Usuario,
    ip: str,
) -> UsuarioDetalle:
    """Reemplaza el rol (uno). La sesión del usuario toma el rol nuevo cuando su
    access token se renueva (AUT-02, minutos).
    """
    with auditar(
        "CAMBIAR_ROL",
        _TABLA_USUARIOS,
        usuario,
        ip,
        f"AUT-09 rol={datos.rol}",
        str(id_usuario),
    ):
        deshacer: Deshacer = []
        try:
            with conn.begin():
                fila = _cargar(conn, id_usuario, bloquear=True)
                actual = _rol(fila)
                if actual != datos.rol:
                    if actual == "ADMIN":
                        _validar_ultimo_admin(conn, fila)
                    key = fila["KeyUsuario"] or _resolver_sin_vinculo(conn, fila)
                    repository.actualizar_rol(conn, id_usuario, datos.rol)
                    _aplicar_rol_en_workos(fila, key, datos.rol, usuario, deshacer)
                    # Deja de ser cajero: se cierra su asignación vigente (otra base)
                    if actual == "CAJERO":
                        with conn_coop.begin():
                            repository.cerrar_asignacion(conn_coop, id_usuario)
        except Exception:
            _deshacer(deshacer)
            raise
        return _detalle(conn, _cargar(conn, id_usuario))

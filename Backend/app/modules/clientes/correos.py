"""E5-04 · Correos secundarios del cliente y marca "verificado por el personal".

El sistema no envía correos: la verificación es una marca manual del personal.
Nunca se escribe un correo en la bitácora de auditoría (ASVS 16.2.5, LOPDP).
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import (
    RESPUESTAS_ERROR,
    ProblemDetailsRoute,
    problema,
    traducir_error_bd,
)
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security import audit
from app.core.security.auth import UsuarioAuditoria, require_auth, require_roles
from app.modules.clientes import repository, service
from app.modules.clientes.schemas import (
    ClienteEmail,
    ClienteEmailNuevo,
    VerificacionEmail,
)
from app.modules.clientes.visibilidad import enmascarar_email
from app.modules.parametros import general

router = APIRouter(
    tags=["clientes"],
    dependencies=[Depends(require_auth)],
    route_class=ProblemDetailsRoute,
    responses={
        **RESPUESTAS_ERROR,
        423: {**RESPUESTAS_ERROR[409], "description": "Locked"},
    },
)

Db = Annotated[Connection, Depends(cooperativa)]
IdCliente = Annotated[int, Path(gt=0, le=2147483647)]
IdEmail = Annotated[int, Path(gt=0, le=2147483647)]

# Mismos roles que el detalle del cliente (CLI04): los correos son datos personales.
_ROLES_CONSULTA = ["ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"]
_ROLES_EDICION = ["ASESOR", "ADMIN"]
_ZONA = ZoneInfo("America/Guayaquil")
_PARAMETRO_MAXIMO = "CLI_MAX_EMAILS_SECUNDARIOS"

# ---------------------------------------------------------------------------
# SQL estático (solo parámetros enlazados)
# ---------------------------------------------------------------------------


_SQL_ACTIVOS = text("""
    SELECT
    IdClienteEmail AS id_cliente_email,
    Email AS email,
    Etiqueta AS etiqueta,
    CAST(CASE WHEN VerificadoPor IS NULL THEN 0 ELSE 1 END AS bit) AS verificado,
    FechaVerificacion AS fecha_verificacion,
    FechaCreacion AS fecha_creacion
    FROM Clientes.ClienteEmail
    WHERE IdCliente = :id_cliente AND Estado = 'A'
    ORDER BY IdClienteEmail
""")

_SQL_ACTIVO = text("""
    SELECT
    IdClienteEmail AS id_cliente_email,
    Email AS email,
    Etiqueta AS etiqueta,
    CAST(CASE WHEN VerificadoPor IS NULL THEN 0 ELSE 1 END AS bit) AS verificado,
    FechaVerificacion AS fecha_verificacion,
    FechaCreacion AS fecha_creacion
    FROM Clientes.ClienteEmail WITH (UPDLOCK, HOLDLOCK)
    WHERE IdClienteEmail = :id_email AND IdCliente = :id_cliente AND Estado = 'A'
""")

_SQL_PRINCIPAL = text("""
    SELECT Email AS email, EmailVerificadoPor AS verificado_por
    FROM Clientes.Cliente
    WHERE IdCliente = :id_cliente
""")

_SQL_INSERTAR = text("""
    SET NOCOUNT ON;
    DECLARE @Nuevo TABLE (IdClienteEmail int);
    INSERT INTO Clientes.ClienteEmail (IdCliente, Email, Etiqueta, CreadoPor)
    OUTPUT INSERTED.IdClienteEmail INTO @Nuevo
    VALUES (:id_cliente, :email, :etiqueta, :creado_por);
    SELECT
    IdClienteEmail AS id_cliente_email,
    Email AS email,
    Etiqueta AS etiqueta,
    CAST(CASE WHEN VerificadoPor IS NULL THEN 0 ELSE 1 END AS bit) AS verificado,
    FechaVerificacion AS fecha_verificacion,
    FechaCreacion AS fecha_creacion
    FROM Clientes.ClienteEmail
    WHERE IdClienteEmail = (SELECT TOP 1 IdClienteEmail FROM @Nuevo);
""")

_SQL_BAJA = text("""
    UPDATE Clientes.ClienteEmail
    SET Estado = 'I'
    WHERE IdClienteEmail = :id_email AND IdCliente = :id_cliente AND Estado = 'A'
""")

_SQL_VERIFICAR_SECUNDARIO = text("""
    SET NOCOUNT ON;
    UPDATE Clientes.ClienteEmail
    SET VerificadoPor = :usuario, FechaVerificacion = SYSUTCDATETIME()
    WHERE IdClienteEmail = :id_email AND IdCliente = :id_cliente
      AND Estado = 'A' AND VerificadoPor IS NULL;
    SELECT
    IdClienteEmail AS id_cliente_email,
    Email AS email,
    Etiqueta AS etiqueta,
    CAST(CASE WHEN VerificadoPor IS NULL THEN 0 ELSE 1 END AS bit) AS verificado,
    FechaVerificacion AS fecha_verificacion,
    FechaCreacion AS fecha_creacion
    FROM Clientes.ClienteEmail
    WHERE IdClienteEmail = :id_email AND IdCliente = :id_cliente;
""")

_SQL_VERIFICAR_PRINCIPAL = text("""
    SET NOCOUNT ON;
    UPDATE Clientes.Cliente
    SET EmailVerificadoPor = :usuario, FechaEmailVerificado = SYSUTCDATETIME()
    WHERE IdCliente = :id_cliente AND EmailVerificadoPor IS NULL;
    SELECT FechaEmailVerificado AS fecha_email_verificado
    FROM Clientes.Cliente
    WHERE IdCliente = :id_cliente;
""")


def _una(conn: Connection, sql: Any, params: dict[str, Any]) -> dict[str, Any] | None:
    fila = conn.execute(sql, params).mappings().first()
    return dict(fila) if fila is not None else None


def listar_activos(conn: Connection, id_cliente: int) -> list[dict[str, Any]]:
    filas = conn.execute(_SQL_ACTIVOS, {"id_cliente": id_cliente}).mappings()
    return [dict(fila) for fila in filas]


def obtener_activo(
    conn: Connection, id_cliente: int, id_email: int
) -> dict[str, Any] | None:
    return _una(conn, _SQL_ACTIVO, {"id_cliente": id_cliente, "id_email": id_email})


def leer_principal(conn: Connection, id_cliente: int) -> dict[str, Any] | None:
    return _una(conn, _SQL_PRINCIPAL, {"id_cliente": id_cliente})


def insertar(
    conn: Connection, id_cliente: int, email: str, etiqueta: str, creado_por: int
) -> dict[str, Any]:
    fila = _una(
        conn,
        _SQL_INSERTAR,
        {
            "id_cliente": id_cliente,
            "email": email,
            "etiqueta": etiqueta,
            "creado_por": creado_por,
        },
    )
    if fila is None:
        raise RuntimeError("La escritura del correo no devolvió la fila.")
    return fila


def dar_de_baja(conn: Connection, id_cliente: int, id_email: int) -> None:
    conn.execute(_SQL_BAJA, {"id_cliente": id_cliente, "id_email": id_email})


def marcar_secundario(
    conn: Connection, id_cliente: int, id_email: int, usuario: int
) -> dict[str, Any]:
    fila = _una(
        conn,
        _SQL_VERIFICAR_SECUNDARIO,
        {"id_cliente": id_cliente, "id_email": id_email, "usuario": usuario},
    )
    if fila is None:
        raise RuntimeError("La escritura del correo no devolvió la fila.")
    return fila


def marcar_principal(conn: Connection, id_cliente: int, usuario: int) -> datetime:
    fila = _una(
        conn, _SQL_VERIFICAR_PRINCIPAL, {"id_cliente": id_cliente, "usuario": usuario}
    )
    if fila is None:
        raise RuntimeError("La escritura del correo no devolvió la fila.")
    return fila["fecha_email_verificado"]


# ---------------------------------------------------------------------------
# Reglas
# ---------------------------------------------------------------------------


def _no_encontrado() -> HTTPException:
    return problema(404, "EMAIL_NO_ENCONTRADO", "No se encontró el correo del cliente.")


def _ya_verificado() -> HTTPException:
    return problema(409, "EMAIL_YA_VERIFICADO", "El correo ya estaba verificado.")


def _cliente_editable(conn: Connection, id_cliente: int) -> None:
    """Bloquea la fila del cliente (UPDLOCK) hasta commit/rollback."""
    cliente = repository.bloquear_cliente(conn, id_cliente)
    if cliente is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "No se encontró el cliente.")
    service.validar_estado_editable(cliente["estado"])


def _maximo_secundarios(conn: Connection) -> int:
    maximo = general.valor(conn, _PARAMETRO_MAXIMO, datetime.now(_ZONA).date())
    if type(maximo) is not int or maximo < 0:
        raise problema(
            503,
            "PARAMETRO_INVALIDO",
            "No se pudo verificar el máximo de correos secundarios.",
        )
    return maximo


def _historial(
    conn: Connection,
    id_cliente: int,
    *,
    tipo: str,
    campo: str,
    anterior: str | None,
    nuevo: str | None,
    motivo: str,
    usuario: int,
    ip: str,
) -> None:
    repository.insertar_historial_cliente(
        conn,
        id_cliente=id_cliente,
        tipo_operacion=tipo,
        campo=campo,
        modificado_por=usuario,
        direccion_ip=ip,
        observaciones=repository.observaciones_cambio(anterior, nuevo, motivo),
        valor_anterior=anterior,
        valor_nuevo=nuevo,
    )


def _en_transaccion[T](conn: Connection, operacion: Callable[[], T]) -> T:
    """Escritura, historial y lectura juntos; rollback ante cualquier fallo (ASVS 2.3.3)."""
    try:
        resultado = operacion()
        conn.commit()
    except DBAPIError as exc:
        conn.rollback()
        raise traducir_error_bd(exc) from None
    except Exception:
        conn.rollback()
        raise
    return resultado


def _auditar(
    id_cliente: int, tabla: str, descripcion: str, usuario: int, ip: str
) -> None:
    # Sin el correo en la descripción (ASVS 16.2.5, LOPDP)
    audit.registrar(
        audit.EventoAuditoria(
            accion="CLI_EDITADO",
            tabla=tabla,
            id_registro=str(id_cliente),
            resultado="Exitoso",
            usuario=usuario,
            ip=ip,
            descripcion=descripcion,
        )
    )


def listar_emails(conn: Connection, id_cliente: int) -> list[ClienteEmail]:
    if repository.obtener_cliente_por_id(conn, id_cliente) is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "No se encontró el cliente.")
    return [ClienteEmail(**fila) for fila in listar_activos(conn, id_cliente)]


def agregar_email(
    conn: Connection,
    id_cliente: int,
    payload: ClienteEmailNuevo,
    usuario: int,
    ip: str,
) -> ClienteEmail:
    def operacion() -> ClienteEmail:
        _cliente_editable(conn, id_cliente)
        maximo = _maximo_secundarios(conn)
        activos = listar_activos(conn, id_cliente)
        if len(activos) >= maximo:
            raise problema(
                422,
                "LIMITE_EMAILS_SECUNDARIOS",
                "El cliente ya tiene el máximo de correos secundarios.",
            )
        principal = leer_principal(conn, id_cliente) or {}
        existentes = {(principal.get("email") or "").lower()}
        existentes.update(fila["email"].lower() for fila in activos)
        if payload.email in existentes:
            raise problema(
                409, "EMAIL_DUPLICADO", "El correo ya está registrado en el cliente."
            )
        fila = insertar(conn, id_cliente, payload.email, payload.etiqueta, usuario)
        _historial(
            conn,
            id_cliente,
            tipo="I",
            campo="EMAIL_SECUNDARIO",
            anterior=None,
            nuevo=payload.email,
            motivo=f"Alta de correo secundario {fila['id_cliente_email']}",
            usuario=usuario,
            ip=ip,
        )
        return ClienteEmail(**fila)

    resultado = _en_transaccion(conn, operacion)
    _auditar(
        id_cliente, "Clientes.ClienteEmail", "Correo secundario agregado", usuario, ip
    )
    return resultado


def eliminar_email(
    conn: Connection, id_cliente: int, id_email: int, usuario: int, ip: str
) -> None:
    def operacion() -> None:
        _cliente_editable(conn, id_cliente)
        if obtener_activo(conn, id_cliente, id_email) is None:
            raise _no_encontrado()
        dar_de_baja(conn, id_cliente, id_email)
        _historial(
            conn,
            id_cliente,
            tipo="D",
            campo="EMAIL_SECUNDARIO.estado",
            anterior="Activo",
            nuevo="Eliminado",
            motivo=f"Baja lógica de correo secundario {id_email}",
            usuario=usuario,
            ip=ip,
        )

    _en_transaccion(conn, operacion)
    _auditar(
        id_cliente, "Clientes.ClienteEmail", "Correo secundario eliminado", usuario, ip
    )


def verificar_principal(
    conn: Connection, id_cliente: int, usuario: int, ip: str
) -> VerificacionEmail:
    def operacion() -> VerificacionEmail:
        _cliente_editable(conn, id_cliente)
        principal = leer_principal(conn, id_cliente)
        if principal is None or not principal.get("email"):
            raise _no_encontrado()
        if principal["verificado_por"] is not None:
            raise _ya_verificado()
        fecha = marcar_principal(conn, id_cliente, usuario)
        _historial(
            conn,
            id_cliente,
            tipo="U",
            campo="EMAIL.verificado",
            anterior="false",
            nuevo="true",
            motivo="Verificación manual del correo principal por el personal",
            usuario=usuario,
            ip=ip,
        )
        return VerificacionEmail(email_verificado=True, fecha_email_verificado=fecha)

    resultado = _en_transaccion(conn, operacion)
    _auditar(id_cliente, "Clientes.Cliente", "Correo principal verificado", usuario, ip)
    return resultado


def verificar_secundario(
    conn: Connection, id_cliente: int, id_email: int, usuario: int, ip: str
) -> ClienteEmail:
    def operacion() -> ClienteEmail:
        _cliente_editable(conn, id_cliente)
        actual = obtener_activo(conn, id_cliente, id_email)
        if actual is None:
            raise _no_encontrado()
        if actual["verificado"]:
            raise _ya_verificado()
        fila = marcar_secundario(conn, id_cliente, id_email, usuario)
        _historial(
            conn,
            id_cliente,
            tipo="U",
            campo="EMAIL_SECUNDARIO.verificado",
            anterior="false",
            nuevo="true",
            motivo=f"Verificación manual del correo secundario {id_email}",
            usuario=usuario,
            ip=ip,
        )
        return ClienteEmail(**fila)

    resultado = _en_transaccion(conn, operacion)
    _auditar(
        id_cliente, "Clientes.ClienteEmail", "Correo secundario verificado", usuario, ip
    )
    return resultado


def _enmascarado(correo: ClienteEmail) -> ClienteEmail:
    # E5-05: el valor completo solo sale por la revelación auditada con MFA.
    return correo.model_copy(update={"email": enmascarar_email(correo.email)})


# ---------------------------------------------------------------------------
# Rutas (el llamador las incluye bajo /clientes)
# ---------------------------------------------------------------------------


@router.get(
    "/{idCliente}/emails",
    operation_id="CLIEmails",
    response_model=list[ClienteEmail],
    dependencies=[Depends(require_roles(*_ROLES_CONSULTA))],
    openapi_extra={"x-roles": _ROLES_CONSULTA},
)
def listar(idCliente: IdCliente, conn: Db) -> list[ClienteEmail]:
    """Correos secundarios activos del cliente, en orden de alta (enmascarados)."""
    return [_enmascarado(c) for c in listar_emails(conn, idCliente)]


@router.post(
    "/{idCliente}/emails",
    operation_id="CLIEmailAgregar",
    response_model=ClienteEmail,
    status_code=201,
    dependencies=[Depends(require_roles(*_ROLES_EDICION))],
    openapi_extra={"x-roles": _ROLES_EDICION},
)
def agregar(
    idCliente: IdCliente,
    payload: ClienteEmailNuevo,
    request: Request,
    usuario: UsuarioAuditoria,
    conn: Db,
) -> ClienteEmail:
    """Agrega un correo secundario (se guarda en minúsculas)."""
    return _enmascarado(
        agregar_email(conn, idCliente, payload, usuario, ip_cliente(request.scope))
    )


@router.delete(
    "/{idCliente}/emails/{idEmail}",
    operation_id="CLIEmailEliminar",
    status_code=204,
    dependencies=[Depends(require_roles(*_ROLES_EDICION))],
    openapi_extra={"x-roles": _ROLES_EDICION},
)
def eliminar(
    idCliente: IdCliente,
    idEmail: IdEmail,
    request: Request,
    usuario: UsuarioAuditoria,
    conn: Db,
) -> Response:
    """Baja lógica de un correo secundario."""
    eliminar_email(conn, idCliente, idEmail, usuario, ip_cliente(request.scope))
    return Response(status_code=204)


@router.post(
    "/{idCliente}/email/verificacion",
    operation_id="CLIEmailVerificar",
    response_model=VerificacionEmail,
    dependencies=[Depends(require_roles(*_ROLES_EDICION))],
    openapi_extra={"x-roles": _ROLES_EDICION},
)
def verificar(
    idCliente: IdCliente,
    request: Request,
    usuario: UsuarioAuditoria,
    conn: Db,
) -> VerificacionEmail:
    """Marca el correo principal como verificado por el personal (sin envío)."""
    return verificar_principal(conn, idCliente, usuario, ip_cliente(request.scope))


@router.post(
    "/{idCliente}/emails/{idEmail}/verificacion",
    operation_id="CLIEmailSecundarioVerificar",
    response_model=ClienteEmail,
    dependencies=[Depends(require_roles(*_ROLES_EDICION))],
    openapi_extra={"x-roles": _ROLES_EDICION},
)
def verificar_correo_secundario(
    idCliente: IdCliente,
    idEmail: IdEmail,
    request: Request,
    usuario: UsuarioAuditoria,
    conn: Db,
) -> ClienteEmail:
    """Marca un correo secundario como verificado por el personal (sin envío)."""
    return _enmascarado(
        verificar_secundario(
            conn, idCliente, idEmail, usuario, ip_cliente(request.scope)
        )
    )

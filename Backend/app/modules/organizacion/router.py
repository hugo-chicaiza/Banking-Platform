"""Organización · Agencias: ORG-01 (POST) y ORG-02 (PATCH, incluye desactivación).

Sin DELETE: la baja es lógica por Estado. Solo ADMIN (decisión del responsable,
2026-11-12). La identidad es la sesión de WorkOS; el UsuarioID de auditoría es el mismo
vínculo que usan todos los módulos (require_auth / UsuarioAuditoria).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente, obtener_trace_id
from app.core.database.db import cooperativa
from app.core.security.auth import (
    Usuario,
    UsuarioAuditoria,
    require_auth,
    require_roles,
)
from app.core.security.operador import auditar
from app.modules.organizacion import service
from app.modules.organizacion.schemas import (
    Agencia,
    AgenciaCreate,
    AgenciaEstado,
    AgenciaEstadoUpdate,
    AgenciaUpdate,
    Entidad,
    EntidadUpdate,
)

_ROLES = ["ADMIN"]

router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]
IdAgenciaPath = Annotated[str, Path(pattern=r"^[0-9A-Z]{3}$")]


@router.post(
    "/agencias",
    tags=["organizacion"],
    operation_id="ORG01",
    response_model=Agencia,
    status_code=201,
    dependencies=[Depends(solo_parametros()), Depends(require_roles(*_ROLES))],
    openapi_extra={"x-roles": _ROLES},
)
def crear_agencia(
    payload: AgenciaCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_auth)],
    creado_por: UsuarioAuditoria,
    conn: Db,
) -> Agencia:
    """Crea una agencia en Estado 'A'. idAgencia lo envía el cliente y no cambia."""
    return service.crear_agencia(
        conn,
        payload,
        creado_por,
        ip_cliente(request.scope),
        obtener_trace_id(request.scope),
    )


@router.patch(
    "/agencias/{id_agencia}",
    tags=["organizacion"],
    operation_id="ORG02",
    response_model=Agencia,
    dependencies=[Depends(solo_parametros()), Depends(require_roles(*_ROLES))],
    openapi_extra={"x-roles": _ROLES},
)
def actualizar_agencia(
    id_agencia: IdAgenciaPath,
    payload: AgenciaUpdate,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_auth)],
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Agencia:
    """Actualización parcial. estado='I' desactiva (con motivo); estado='A' reactiva."""
    return service.actualizar_agencia(
        conn,
        id_agencia,
        payload,
        modificado_por,
        ip_cliente(request.scope),
        obtener_trace_id(request.scope),
    )


# Endpoint heredado del compañero: conservar ruta, operación y auditoría.
def _sin_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


@router.patch(
    "/agencias/{id_agencia}/estado",
    response_model=AgenciaEstado,
    tags=["organizacion"],
    operation_id="AgenciaCambiarEstado",
    openapi_extra={"x-roles": ["ADMIN"]},
    dependencies=[Depends(solo_parametros()), Depends(_sin_cache)],
)
def cambiar_estado(
    id_agencia: Annotated[str, Path(min_length=3, max_length=3)],
    datos: AgenciaEstadoUpdate,
    conn: Db,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_roles("ADMIN"))],
):
    resultado, anterior = service.cambiar_estado(conn, id_agencia, datos.estado)
    if anterior != resultado.estado:
        with auditar(
            "CAMBIAR_ESTADO_AGENCIA",
            "Organizacion.Agencia",
            usuario,
            ip_cliente(request.scope),
            f"estado_anterior={anterior} estado_nuevo={resultado.estado}",
            id_agencia,
        ):
            pass
    return resultado


@router.get(
    "/organizacion/entidad",
    tags=["Organización"],
    response_model=Entidad,
    operation_id="EntidadObtener",
    summary="Obtener la entidad",
    openapi_extra={"x-roles": ["ASESOR", "ADMIN"]},
    dependencies=[
        Depends(_sin_cache),
        Depends(require_roles("ASESOR", "ADMIN")),
        Depends(solo_parametros()),
    ],
)
def obtener_entidad(conn: Db) -> Entidad:
    """Devuelve la entidad con IdEntidad = 1, incluso si está inactiva.

    Requiere sesión y rol ASESOR o ADMIN. Si falta el registro, responde
    404 ENTIDAD_NO_ENCONTRADA.
    """
    return service.obtener_entidad(conn)


@router.patch(
    "/organizacion/entidad",
    tags=["Organización"],
    response_model=Entidad,
    operation_id="EntidadEditar",
    summary="Editar parcialmente la entidad",
    openapi_extra={"x-roles": ["ADMIN"]},
    dependencies=[Depends(solo_parametros()), Depends(_sin_cache)],
)
def editar_entidad(
    datos: EntidadUpdate,
    conn: Db,
    request: Request,
    modificado_por: UsuarioAuditoria,
    usuario: Annotated[Usuario, Depends(require_roles("ADMIN"))],
) -> Entidad:
    """Actualiza IdEntidad = 1 y devuelve todos sus datos persistidos.

    Requiere ADMIN. Envíe al menos un campo editable. Omitir un campo conserva
    su valor y null vacía los campos anulables. Los campos idEntidad,
    fechaRegistro y modificadoPor son administrados por el backend.
    ModificadoPor se obtiene de la sesión. Un cuerpo inválido responde
    400 DATOS_INVALIDOS. Una entidad inexistente responde
    404 ENTIDAD_NO_ENCONTRADA. Repetir los valores actuales devuelve 200
    sin otra escritura de auditoría. Los cambios efectivos se auditan
    después del commit mediante el mecanismo best-effort existente.
    """
    resultado, campos = service.editar_entidad(conn, datos, modificado_por)
    if campos:
        with auditar(
            "EDITAR_ENTIDAD",
            "Organizacion.Entidad",
            usuario,
            ip_cliente(request.scope),
            "campos=" + ",".join(campos),
            str(resultado.id_entidad),
        ):
            pass
    return resultado

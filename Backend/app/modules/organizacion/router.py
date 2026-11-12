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
)

_ROLES = ["ADMIN"]

router = APIRouter(
    prefix="/agencias",
    tags=["organizacion"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth), Depends(require_roles(*_ROLES))],
)

Db = Annotated[Connection, Depends(cooperativa)]
IdAgenciaPath = Annotated[str, Path(pattern=r"^[0-9A-Z]{3}$")]


@router.post(
    "",
    operation_id="ORG01",
    response_model=Agencia,
    status_code=201,
    dependencies=[Depends(solo_parametros())],
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
    "/{id_agencia}",
    operation_id="ORG02",
    response_model=Agencia,
    dependencies=[Depends(solo_parametros())],
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
    "/{id_agencia}/estado",
    response_model=AgenciaEstado,
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

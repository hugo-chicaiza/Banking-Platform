"""HTTP E1-12. Las escrituras de parámetros son del rol ADMIN (sin permiso de WorkOS propio)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import UsuarioAuditoria, require_auth, require_roles
from app.modules.parametros import service
from app.modules.parametros.schemas import (
    AsociarComision,
    Comision,
    ComisionCreate,
    ComisionUpdate,
    Exoneracion,
    ExoneracionCreate,
    ExoneracionUpdate,
)

router = APIRouter(
    prefix="/parametros",
    tags=["parametros"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth)],
)
Db = Annotated[Connection, Depends(cooperativa)]
IdComision = Annotated[int, Path(alias="idComision", ge=1, le=2_147_483_647)]
IdExoneracion = Annotated[int, Path(alias="idExoneracion", ge=1, le=2_147_483_647)]
_LECTURA = ("ADMIN", "SUPERVISOR", "ASESOR")
_ESCRITURA = [Depends(require_roles("ADMIN")), Depends(solo_parametros())]


@router.get(
    "/comisiones",
    response_model=list[Comision],
    dependencies=[Depends(require_roles(*_LECTURA)), Depends(solo_parametros())],
)
def listar_comisiones(conn: Db) -> list[Comision]:
    return service.listar_comisiones(conn)


@router.post(
    "/comisiones", response_model=Comision, status_code=201, dependencies=_ESCRITURA
)
def crear_comision(
    payload: ComisionCreate | AsociarComision,
    actor: UsuarioAuditoria,
    request: Request,
    conn: Db,
) -> Comision:
    """Crea tarifa y asociación, o asocia una tarifa existente por idComision."""
    return service.crear_comision(conn, payload, actor, ip_cliente(request.scope))


@router.patch(
    "/comisiones/{idComision}",
    response_model=Comision,
    dependencies=_ESCRITURA,
    responses={501: {"description": "Cambio de valor pendiente del flujo E1-10"}},
)
def actualizar_comision(
    id_comision: IdComision,
    payload: ComisionUpdate,
    actor: UsuarioAuditoria,
    request: Request,
    conn: Db,
) -> Comision:
    return service.actualizar_comision(
        conn, id_comision, payload, actor, ip_cliente(request.scope)
    )


@router.get(
    "/exoneraciones",
    response_model=list[Exoneracion],
    dependencies=[
        Depends(require_roles(*_LECTURA)),
        Depends(solo_parametros("idComision")),
    ],
)
def listar_exoneraciones(
    conn: Db,
    id_comision: Annotated[
        int | None, Query(alias="idComision", ge=1, le=2_147_483_647)
    ] = None,
) -> list[Exoneracion]:
    return service.listar_exoneraciones(conn, id_comision)


@router.post(
    "/exoneraciones",
    response_model=Exoneracion,
    status_code=201,
    dependencies=_ESCRITURA,
)
def crear_exoneracion(
    payload: ExoneracionCreate, actor: UsuarioAuditoria, request: Request, conn: Db
) -> Exoneracion:
    return service.crear_exoneracion(conn, payload, actor, ip_cliente(request.scope))


@router.patch(
    "/exoneraciones/{idExoneracion}",
    response_model=Exoneracion,
    dependencies=_ESCRITURA,
)
def actualizar_exoneracion(
    id_exoneracion: IdExoneracion,
    payload: ExoneracionUpdate,
    actor: UsuarioAuditoria,
    request: Request,
    conn: Db,
) -> Exoneracion:
    return service.actualizar_exoneracion(
        conn, id_exoneracion, payload, actor, ip_cliente(request.scope)
    )

"""HTTP E1-12. Las escrituras de parámetros son del rol ADMIN (sin permiso de WorkOS propio)."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.core.api.errors import (
    RESPUESTAS_ERROR,
    ProblemDetailsRoute,
    problema,
    solo_parametros,
)
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import (
    UsuarioActual,
    UsuarioAuditoria,
    require_auth,
    require_roles,
)
from app.modules.aprobaciones import router as aprobaciones
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.registro import Objetivo
from app.modules.parametros import mantenimiento, repository, service
from app.modules.parametros.aprobacion_comision import OPERACION_TARIFA
from app.modules.parametros.schemas import (
    AsociarComision,
    Comision,
    ComisionCreate,
    ComisionUpdate,
    Exoneracion,
    ExoneracionCreate,
    ExoneracionUpdate,
    TarifaVigente,
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
    responses={202: {"model": SolicitudAceptada}},
)
def actualizar_comision(
    id_comision: IdComision,
    payload: ComisionUpdate,
    actor: UsuarioAuditoria,
    request: Request,
    conn: Db,
    usuario: UsuarioActual,
) -> Comision | JSONResponse:
    if service.cambio_sensible(conn, id_comision, payload):
        if payload.model_fields_set - {"valor", "vigencia_desde"}:
            raise problema(
                422,
                "CAMBIO_TARIFA_MIXTO",
                "Envíe el cambio de tarifa separado de los metadatos.",
            )
        hoy = service.hoy()
        conn.rollback()
        actor_aprobaciones = aprobaciones.actual(usuario)
        id_ = aprobaciones.servicio().solicitar(
            actor_aprobaciones,
            OPERACION_TARIFA.codigo,
            Objetivo(OPERACION_TARIFA.tipo_objetivo, str(id_comision), None),
            {
                "valor": str(payload.valor) if payload.valor is not None else None,
                "vigenciaDesde": (
                    payload.vigencia_desde or hoy + timedelta(days=1)
                ).isoformat(),
            },
            hoy,
            aprobaciones.contexto(request, usuario),
        )
        return JSONResponse(
            status_code=202,
            content=SolicitudAceptada(id_solicitud=id_).model_dump(by_alias=True),
        )
    return service.actualizar_comision(
        conn, id_comision, payload, actor, ip_cliente(request.scope), usuario=usuario
    )


@router.get(
    "/comisiones/{idComision}/tarifa",
    response_model=TarifaVigente,
    dependencies=[Depends(require_roles(*_LECTURA)), Depends(solo_parametros("fecha"))],
)
def consultar_tarifa(id_comision: IdComision, fecha: date, conn: Db) -> TarifaVigente:
    fila = repository.tarifa_comision(conn, id_comision, fecha)
    if fila is None:
        raise problema(
            404, "TARIFA_NO_ENCONTRADA", "No hay una tarifa para la fecha consultada."
        )
    return TarifaVigente.model_validate(fila)


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


# Despues de las rutas estaticas E1-12 para evitar capturarlas con /{clave}.
router_e112 = router
router = APIRouter()
router.include_router(router_e112)
router.include_router(mantenimiento.router, prefix="/parametros")

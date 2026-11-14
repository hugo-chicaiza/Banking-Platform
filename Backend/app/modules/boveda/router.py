"""Las seis rutas BOV: sesión, roles, CSRF y errores F-04."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, require_auth, require_roles
from app.core.security.operador import IdInterno
from app.modules.boveda import service
from app.modules.boveda.schemas import (
    INT32_MAX,
    INT64_MAX,
    ArqueoBoveda,
    ArqueoBovedaRequest,
    Boveda,
    MovimientoBoveda,
    MovimientoBovedaRequest,
    PageMovimientoBoveda,
    TipoBoveda,
    TipoMovimiento,
)


def _sin_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(
    prefix="/boveda",
    tags=["Bóveda"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth), Depends(_sin_cache)],
)
Conexion = Annotated[Connection, Depends(cooperativa)]
IdBoveda = Annotated[int, Path(alias="idBoveda", gt=0, le=INT32_MAX)]


@router.get("/bovedas", response_model=list[Boveda], operation_id="BOV01")
def listar_bovedas(
    usuario: Annotated[
        Usuario, Depends(require_roles("SUPERVISOR", "CONTADOR", "ADMIN"))
    ],
    conn: Conexion,
    _: Annotated[None, Depends(solo_parametros("idAgencia", "tipo"))],
    id_agencia: Annotated[
        str | None, Query(alias="idAgencia", pattern=r"^\d{3}$")
    ] = None,
    tipo: TipoBoveda | None = None,
) -> list[Boveda]:
    return service.listar_bovedas(conn, usuario, id_agencia, tipo)


@router.get("/bovedas/{idBoveda}", response_model=Boveda, operation_id="BOV02")
def obtener_boveda(
    id_boveda: IdBoveda,
    usuario: Annotated[
        Usuario, Depends(require_roles("SUPERVISOR", "CONTADOR", "ADMIN"))
    ],
    conn: Conexion,
    _: Annotated[None, Depends(solo_parametros())],
) -> Boveda:
    return service.obtener_boveda(conn, usuario, id_boveda)


@router.get(
    "/bovedas/{idBoveda}/movimientos",
    response_model=PageMovimientoBoveda,
    operation_id="BOV03",
)
def listar_movimientos(
    id_boveda: IdBoveda,
    usuario: Annotated[
        Usuario, Depends(require_roles("SUPERVISOR", "CONTADOR", "AUDITOR"))
    ],
    conn: Conexion,
    _: Annotated[
        None,
        Depends(
            solo_parametros(
                "tipoMovimiento", "desde", "hasta", "page", "pageSize", "sort"
            )
        ),
    ],
    tipo_movimiento: Annotated[
        TipoMovimiento | None, Query(alias="tipoMovimiento")
    ] = None,
    desde: date | None = None,
    hasta: date | None = None,
    page: Annotated[int, Query(ge=1, le=INT32_MAX)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: str = "fechaMovimiento,desc",
) -> PageMovimientoBoveda:
    return service.listar_movimientos(
        conn, usuario, id_boveda, tipo_movimiento, desde, hasta, page, page_size, sort
    )


@router.post(
    "/bovedas/{idBoveda}/movimientos",
    response_model=list[MovimientoBoveda],
    status_code=201,
    operation_id="BOV04",
)
def registrar_movimiento(
    id_boveda: IdBoveda,
    datos: MovimientoBovedaRequest,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_roles("SUPERVISOR"))],
    id_interno: IdInterno,
    conn: Conexion,
    _: Annotated[None, Depends(solo_parametros())],
    clave: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=64,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ] = None,
) -> list[MovimientoBoveda]:
    return service.registrar_movimiento(
        conn, usuario, id_interno, id_boveda, datos, ip_cliente(request.scope), clave
    )


@router.post(
    "/bovedas/{idBoveda}/arqueos",
    response_model=ArqueoBoveda,
    status_code=201,
    operation_id="BOV05",
)
def registrar_arqueo(
    id_boveda: IdBoveda,
    datos: ArqueoBovedaRequest,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_roles("SUPERVISOR", "AUDITOR"))],
    id_interno: IdInterno,
    conn: Conexion,
    _: Annotated[None, Depends(solo_parametros())],
) -> ArqueoBoveda:
    return service.registrar_arqueo(
        conn, usuario, id_interno, id_boveda, datos, ip_cliente(request.scope)
    )


@router.post(
    "/arqueos/{idArqueoBoveda}/aprobacion",
    response_model=ArqueoBoveda,
    operation_id="BOV06",
)
def aprobar_arqueo(
    id_arqueo: Annotated[int, Path(alias="idArqueoBoveda", gt=0, le=INT64_MAX)],
    request: Request,
    usuario: Annotated[Usuario, Depends(require_roles("SUPERVISOR"))],
    id_interno: IdInterno,
    conn: Conexion,
    _: Annotated[None, Depends(solo_parametros())],
) -> ArqueoBoveda:
    return service.aprobar_arqueo(
        conn, usuario, id_interno, id_arqueo, ip_cliente(request.scope)
    )

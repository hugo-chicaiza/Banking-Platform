"""TRX-01..TRX-03 · Consulta y reverso supervisado de transacciones."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, require_roles
from app.modules.caja.schemas import INT32_MAX
from app.modules.transacciones import service
from app.modules.transacciones.schemas import PageTransaccion


def _sin_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(
    prefix="/transacciones",
    tags=["Transacciones"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(_sin_cache)],
)

Conexion = Annotated[Connection, Depends(cooperativa)]


# TRX-01. Roles: SUPERVISOR (su agencia), AUDITOR, CONTADOR, ADMIN
@router.get("", response_model=PageTransaccion, operation_id="TRX01")
def listar_transacciones(
    usuario: Annotated[
        Usuario,
        Depends(require_roles("SUPERVISOR", "AUDITOR", "CONTADOR", "ADMIN")),
    ],
    _parametros: Annotated[
        None,
        Depends(
            solo_parametros(
                "idCuenta",
                "tipoTransaccion",
                "estado",
                "idCanal",
                "idAgencia",
                "desde",
                "hasta",
                "page",
                "pageSize",
                "sort",
            )
        ),
    ],
    conn: Conexion,
    id_cuenta: Annotated[
        int | None, Query(alias="idCuenta", gt=0, le=INT32_MAX)
    ] = None,
    tipo_transaccion: Annotated[
        str | None, Query(alias="tipoTransaccion", min_length=1, max_length=30)
    ] = None,
    estado: Annotated[str | None, Query(min_length=1, max_length=12)] = None,
    id_canal: Annotated[int | None, Query(alias="idCanal", gt=0, le=INT32_MAX)] = None,
    id_agencia: Annotated[
        str | None,
        Query(alias="idAgencia", min_length=3, max_length=3, pattern=r"^\d{3}$"),
    ] = None,
    desde: date | None = None,
    hasta: date | None = None,
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: Annotated[str | None, Query(max_length=40)] = None,
) -> PageTransaccion:
    return service.listar_transacciones(
        conn,
        usuario,
        id_cuenta,
        tipo_transaccion,
        estado,
        id_canal,
        id_agencia,
        desde,
        hasta,
        page,
        page_size,
        sort,
    )

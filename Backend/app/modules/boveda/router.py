"""Rutas de bóveda: sesión, roles, permisos, CSRF y errores F-04."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
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
    EstadoArqueo,
    PageArqueoBoveda,
    PageMovimientoBoveda,
    TipoArqueo,
    TipoBoveda,
    TipoMovimiento,
)
from app.modules.boveda.solicitudes.router import router as solicitudes_router


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
        Usuario, Depends(require_roles("SUPERVISOR", "CONTADOR", "AUDITOR", "ADMIN"))
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
    response_model=None,
    status_code=410,
    operation_id="BOV04",
    deprecated=True,
    responses={
        410: {
            **RESPUESTAS_ERROR[409],
            "description": "Crear una solicitud y obtener aprobación independiente.",
        }
    },
)
def registrar_movimiento(
    id_boveda: IdBoveda,
    usuario: Annotated[Usuario, Depends(require_roles("SUPERVISOR", "ADMIN"))],
    _: Annotated[None, Depends(solo_parametros())],
) -> None:
    service.registrar_movimiento()


@router.get(
    "/bovedas/{idBoveda}/arqueos",
    response_model=PageArqueoBoveda,
    operation_id="BOVArqueos",
)
def listar_arqueos(
    id_boveda: IdBoveda,
    usuario: Annotated[
        Usuario, Depends(require_roles("SUPERVISOR", "CONTADOR", "AUDITOR", "ADMIN"))
    ],
    conn: Conexion,
    _: Annotated[
        None,
        Depends(
            solo_parametros(
                "desde", "hasta", "estado", "tipoArqueo", "page", "pageSize"
            )
        ),
    ],
    desde: date | None = None,
    hasta: date | None = None,
    estado: EstadoArqueo | None = None,
    tipo_arqueo: Annotated[TipoArqueo | None, Query(alias="tipoArqueo")] = None,
    page: Annotated[int, Query(ge=1, le=INT32_MAX)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> PageArqueoBoveda:
    """Historial por bóveda, de más reciente a más antiguo, con días inclusivos."""
    return service.listar_arqueos(
        conn, usuario, id_boveda, desde, hasta, estado, tipo_arqueo, page, page_size
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
    usuario: Annotated[
        Usuario, Depends(require_roles("SUPERVISOR", "AUDITOR", "ADMIN"))
    ],
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
    usuario: Annotated[Usuario, Depends(require_roles("SUPERVISOR", "ADMIN"))],
    id_interno: IdInterno,
    conn: Conexion,
    _: Annotated[None, Depends(solo_parametros())],
) -> ArqueoBoveda:
    return service.aprobar_arqueo(
        conn, usuario, id_interno, id_arqueo, ip_cliente(request.scope)
    )


router.include_router(solicitudes_router)

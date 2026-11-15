from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.database.db import cooperativa
from app.core.security.auth import require_auth, require_roles
from app.modules.contabilidad import service
from app.modules.contabilidad.schemas import (
    INT32_MAX,
    Asiento,
    CuentaContable,
    FechaContable,
    PageAsiento,
)

router = APIRouter(
    prefix="/contabilidad",
    tags=["contabilidad"],
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]

# ---------------------------------------------------------------------------
# AC-02 · Fecha contable
# ---------------------------------------------------------------------------
# Roles: AUTH (cualquier usuario autenticado)
# OJO: /fechas-contables/actual debe declararse ANTES que /fechas-contables/{fecha};
# si no, FastAPI tomaría "actual" como si fuera una fecha.


@router.get("/fechas-contables/actual", response_model=FechaContable)
def fecha_contable_actual(conn: Db) -> Any:
    """CON-02 · Fecha contable vigente (según la hora de corte de las 19:00)."""
    return service.obtener_fecha_contable_actual(conn)


@router.get("/fechas-contables/{fecha}", response_model=FechaContable)
def fecha_contable_por_fecha(
    conn: Db,
    fecha: Annotated[str, Path(description="Día calendario, formato YYYY-MM-DD")],
) -> Any:
    """CON-01 · Fila del calendario contable de una fecha (día hábil, feriado, corte)."""
    return service.obtener_fecha_contable(conn, fecha)


# ---------------------------------------------------------------------------
# AC-03 · Plan de cuentas
# ---------------------------------------------------------------------------
# Roles: CONTADOR, AUDITOR, ADMIN
_ROLES_CUENTAS_CONTABLES = ["CONTADOR", "AUDITOR", "ADMIN"]
_cuentas_contables_router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles(*_ROLES_CUENTAS_CONTABLES))],
)


@_cuentas_contables_router.get(
    "/cuentas-contables",
    operation_id="CON03",
    response_model=list[CuentaContable],
    dependencies=[Depends(solo_parametros("q", "imputable"))],
    openapi_extra={"x-roles": _ROLES_CUENTAS_CONTABLES},
)
def listar_cuentas_contables(
    conn: Db,
    q: Annotated[
        str | None,
        Query(min_length=1, max_length=100, description="Código o nombre"),
    ] = None,
    imputable: Annotated[
        bool | None, Query(description="Solo las cuentas imputables")
    ] = None,
) -> Any:
    """CON-03 · Plan de cuentas (CUC), con filtro por texto y por imputable.

    Lista ordenada por código; la jerarquía va en idCuentaSuperior.
    """
    return service.listar_cuentas_contables(conn, q, imputable)


router.include_router(_cuentas_contables_router)


# ---------------------------------------------------------------------------
# AC-03 · Asientos contables (consulta)
# ---------------------------------------------------------------------------
# Roles: CONTADOR, AUDITOR, ADMIN
_ROLES_ASIENTOS = ["CONTADOR", "AUDITOR", "ADMIN"]
_asientos_router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles(*_ROLES_ASIENTOS))],
)
# Origen y estado: texto libre (se normaliza en el servicio), no un enum fijo,
# porque pueden aparecer valores nuevos.


@_asientos_router.get(
    "/asientos",
    operation_id="CON04",
    response_model=PageAsiento,
    dependencies=[
        Depends(
            solo_parametros(
                "fecha", "origen", "idAgencia", "estado", "page", "pageSize", "sort"
            )
        )
    ],
    openapi_extra={"x-roles": _ROLES_ASIENTOS},
)
def listar_asientos(
    conn: Db,
    fecha: Annotated[
        str | None, Query(max_length=10, description="Fecha del asiento, YYYY-MM-DD")
    ] = None,
    origen: Annotated[str | None, Query(min_length=1, max_length=20)] = None,
    id_agencia: Annotated[
        str | None, Query(alias="idAgencia", min_length=3, max_length=3)
    ] = None,
    estado: Annotated[str | None, Query(min_length=1, max_length=20)] = None,
    page: Annotated[int, Query(ge=1, le=INT32_MAX)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: Annotated[
        str | None, Query(max_length=40, description="campo,asc|desc")
    ] = None,
) -> Any:
    """CON-04 · Asientos paginados; por defecto fechaAsiento desc. Sin detalle."""
    return service.listar_asientos(
        conn,
        fecha=fecha,
        origen=origen,
        id_agencia=id_agencia,
        estado=estado,
        page=page,
        page_size=page_size,
        sort=sort,
    )


@_asientos_router.get(
    "/asientos/{idAsiento}",
    operation_id="CON05",
    response_model=Asiento,
    dependencies=[Depends(solo_parametros())],
    openapi_extra={"x-roles": _ROLES_ASIENTOS},
)
def obtener_asiento(
    conn: Db,
    id_asiento: Annotated[int, Path(alias="idAsiento", ge=1, le=INT32_MAX)],
) -> Any:
    """CON-05 · Asiento con su detalle (líneas ordenadas por IdMovimientoContable)."""
    return service.obtener_asiento(conn, id_asiento)


router.include_router(_asientos_router)

"""CAJ-01..CAJ-18 · Caja: jornadas, dotaciones, ventanilla, cuadre y cierre.

El router exige sesión mediante require_auth y cada endpoint valida sus roles.
Las operaciones de escritura quedan sujetas al control CSRF de usuario_actual.
Las operaciones que necesitan un identificador interno deben fallar cerradas
si el usuario de WorkOS todavía no está vinculado.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, require_auth, require_roles
from app.modules.caja import service
from app.modules.caja.schemas import CajaFisica, PageJornada


def _sin_cache(response: Response) -> None:
    """Evita almacenar información de caja en cachés."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(
    prefix="/caja",
    tags=["Caja"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[
        Depends(require_auth),
        Depends(_sin_cache),
    ],
)

Conexion = Annotated[Connection, Depends(cooperativa)]

CodigoAgencia = Annotated[
    str | None,
    Query(
        alias="idAgencia",
        min_length=3,
        max_length=3,
        pattern=r"^\d{3}$",
    ),
]


# ---------------------------------------------------------------------
# CAJ-01: GET /api/v1/caja/cajas-fisicas
# Roles: CAJERO, SUPERVISOR, ADMIN
# ---------------------------------------------------------------------


@router.get(
    "/cajas-fisicas",
    response_model=list[CajaFisica],
    operation_id="CAJ01",
)
def listar_cajas_fisicas(
    usuario: Annotated[
        Usuario,
        Depends(require_roles("CAJERO", "SUPERVISOR", "ADMIN")),
    ],
    _parametros: Annotated[
        None,
        Depends(solo_parametros("idAgencia", "activa")),
    ],
    conn: Conexion,
    id_agencia: CodigoAgencia = None,
    activa: bool | None = None,
) -> list[CajaFisica]:
    """Consulta cajas físicas aplicando los permisos de agencia."""

    return service.listar_cajas_fisicas(
        conn,
        usuario,
        id_agencia,
        activa,
    )


# ---------------------------------------------------------------------
# CAJ-02: GET /api/v1/caja/jornadas
# Roles: SUPERVISOR, CONTADOR, AUDITOR
# ---------------------------------------------------------------------


@router.get(
    "/jornadas",
    response_model=PageJornada,
    operation_id="CAJ02",
)
def consultar_jornadas(
    usuario: Annotated[
        Usuario,
        Depends(require_roles("SUPERVISOR", "CONTADOR", "AUDITOR")),
    ],
    _parametros: Annotated[
        None,
        Depends(
            solo_parametros(
                "idAgencia",
                "idUsuario",
                "estado",
                "desde",
                "hasta",
                "page",
                "pageSize",
                "sort",
            )
        ),
    ],
    conn: Conexion,
    id_agencia: CodigoAgencia = None,
    id_usuario: Annotated[
        int | None,
        Query(alias="idUsuario", ge=1),
    ] = None,
    estado: Literal["ABIERTA", "CERRADA", "CANCELADA"] | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[
        int,
        Query(alias="pageSize", ge=1, le=100),
    ] = 20,
    sort: str = "fechaHoraApertura,desc",
) -> PageJornada:
    """Consulta jornadas con filtros, paginación y aislamiento por agencia."""

    return service.listar_jornadas(
        conn,
        usuario=usuario,
        id_agencia=id_agencia,
        id_usuario=id_usuario,
        estado=estado,
        desde=desde,
        hasta=hasta,
        page=page,
        page_size=page_size,
        sort=sort,
    )

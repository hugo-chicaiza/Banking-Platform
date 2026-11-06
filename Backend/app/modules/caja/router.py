"""CAJ-01..CAJ-18 · Caja: jornadas, dotaciones, ventanilla, cuadre y cierre.

El router exige sesión (`require_auth`) y cada ruta su rol con `require_roles`. Las
rutas que escriben pasan además por el control CSRF de `usuario_actual`. Las que necesitan el id interno del usuario fallan cerradas con
403 USUARIO_INTERNO_NO_VINCULADO mientras no exista ese vínculo (ver
app/core/security/operador.py).
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
    """Datos de caja y de clientes: que no queden en cachés de navegador ni proxy."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(
    prefix="/caja",
    tags=["Caja"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth), Depends(_sin_cache)],
)

Conexion = Annotated[Connection, Depends(cooperativa)]
CodigoAgencia = Annotated[
    str | None, Query(alias="idAgencia", min_length=3, max_length=3, pattern=r"^\d{3}$")
]


def _roles(*roles: str) -> object:
    return Depends(require_roles(*roles))


# CAJ-01. Roles: CAJERO, SUPERVISOR, ADMIN
@router.get("/cajas-fisicas", response_model=list[CajaFisica], operation_id="CAJ01")
def listar_cajas_fisicas(
    usuario: Annotated[Usuario, _roles("CAJERO", "SUPERVISOR", "ADMIN")],
    _parametros: Annotated[None, Depends(solo_parametros("idAgencia", "activa"))],
    conn: Conexion,
    id_agencia: CodigoAgencia = None,
    activa: bool | None = None,
) -> list[CajaFisica]:
    """Cajas de la agencia del usuario (ADMIN puede pedir cualquiera o todas)."""
    return service.listar_cajas_fisicas(conn, usuario, id_agencia, activa)


# --- CAJ-02: GET /api/v1/caja/jornadas -------------------------------


@router.get(
    "/jornadas",
    response_model=PageJornada,
    operation_id="CAJ02",
    dependencies=[Depends(require_roles("SUPERVISOR", "CONTADOR", "AUDITOR"))],
)
def consultar_jornadas(
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
    id_usuario: Annotated[int | None, Query(alias="idUsuario", ge=1)] = None,
    estado: Literal["ABIERTA", "CERRADA", "CANCELADA"] | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: str = "fechaHoraApertura,desc",
) -> PageJornada:
    """Consulta jornadas con filtros y paginación.

    TODO W4:
    - Incorporar require_roles(SUPERVISOR, CONTADOR, AUDITOR).
    - Validar acceso a la agencia solicitada.
    - Activar pruebas de autenticación y autorización.
    """

    return service.listar_jornadas(
        conn,
        id_agencia=id_agencia,
        id_usuario=id_usuario,
        estado=estado,
        desde=desde,
        hasta=hasta,
        page=page,
        page_size=page_size,
        sort=sort,
    )

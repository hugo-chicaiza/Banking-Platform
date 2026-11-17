from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.database.db import cooperativa
from app.core.security.auth import (
    UsuarioActual,
    require_auth,
    require_permiso,
    require_roles,
)
from app.core.security.operador import IdInterno, auditar, exigir_id_interno
from app.modules.contabilidad import importaciones, service
from app.modules.contabilidad.schemas import (
    INT32_MAX,
    Asiento,
    CuentaContable,
    CuentaContableCrear,
    CuentaContableEditar,
    CuentaContableEstado,
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
# #206 · Alta, edición, estado y baja de cuentas (contrato: el servicio da 501)
# ---------------------------------------------------------------------------
# Roles: solo CONTADOR. El AUDITOR (y el ADMIN) solo leen el plan con CON-03.
_ROLES_ESCRITURA_CUENTAS = ["CONTADOR"]
_cuentas_escritura_router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[
        Depends(require_permiso("contabilidad:editar")),
        Depends(solo_parametros()),
    ],
)
IdCuentaContable = Annotated[int, Path(alias="idCuentaContable", ge=1, le=INT32_MAX)]


def _error(status: int, descripcion: str) -> dict[str, Any]:
    """Respuesta de error de RESPUESTAS_ERROR con la descripción de la ruta."""
    return {**RESPUESTAS_ERROR[status], "description": descripcion}


_PENDIENTE: dict[int | str, dict[str, Any]] = {
    202: {"description": "Pendiente de aprobación. Sin cuerpo."}
}
_NO_HABILITADA = {
    501: {
        "description": "OPERACION_NO_HABILITADA: contrato aún sin lógica.",
        "content": RESPUESTAS_ERROR[500]["content"],
    }
}
_NO_EXISTE = {404: _error(404, "CUENTA_NO_ENCONTRADA: la cuenta no existe.")}


@_cuentas_escritura_router.post(
    "/cuentas-contables",
    operation_id="CON03Crear",
    status_code=201,
    response_model=CuentaContable,
    responses={
        **_PENDIENTE,
        404: _error(404, "CUENTA_SUPERIOR_NO_ENCONTRADA: la cuenta padre no existe."),
        409: _error(409, "CODIGO_DUPLICADO: ya existe una cuenta con ese código."),
        422: _error(
            422,
            "CODIGO_NO_CORRESPONDE_AL_PADRE: el código no empieza con el del padre.",
        ),
        **_NO_HABILITADA,
    },
    openapi_extra={"x-roles": _ROLES_ESCRITURA_CUENTAS},
)
def crear_cuenta_contable(conn: Db, datos: CuentaContableCrear) -> Any:
    """Alta de una cuenta del plan: 201 con la cuenta o 202 si queda pendiente."""
    return service.crear_cuenta_contable(conn, datos)


@_cuentas_escritura_router.patch(
    "/cuentas-contables/{idCuentaContable}",
    operation_id="CON03Editar",
    response_model=CuentaContable,
    responses={**_NO_EXISTE, 409: _error(409, "CUENTA_DEL_REGULADOR")},
    openapi_extra={"x-roles": _ROLES_ESCRITURA_CUENTAS},
)
def editar_cuenta_contable(
    conn: Db,
    id_cuenta: IdCuentaContable,
    datos: CuentaContableEditar,
    id_interno: IdInterno,
    usuario: UsuarioActual,
    request: Request,
) -> Any:
    """Renombra un auxiliar contable."""
    actor = exigir_id_interno(id_interno)
    with auditar(
        "CON_CUENTA_EDITADA",
        "Contabilidad.CuentasContables",
        usuario,
        request.client.host if request.client else "",
        "",
        str(id_cuenta),
    ):
        return service.editar_cuenta_contable(conn, id_cuenta, datos, actor)


@_cuentas_escritura_router.patch(
    "/cuentas-contables/{idCuentaContable}/estado",
    operation_id="CON03Estado",
    response_model=CuentaContable,
    responses={
        **_PENDIENTE,
        **_NO_EXISTE,
        409: _error(409, "CUENTA_CON_SALDO: no se desactiva una cuenta con saldo."),
        **_NO_HABILITADA,
    },
    openapi_extra={"x-roles": _ROLES_ESCRITURA_CUENTAS},
)
def cambiar_estado_cuenta_contable(
    conn: Db, id_cuenta: IdCuentaContable, datos: CuentaContableEstado
) -> Any:
    """Activa o desactiva la cuenta: 200 con la cuenta o 202 si queda pendiente."""
    return service.cambiar_estado_cuenta_contable(conn, id_cuenta, datos)


@_cuentas_escritura_router.delete(
    "/cuentas-contables/{idCuentaContable}",
    operation_id="CON03Eliminar",
    status_code=204,
    response_class=Response,
    responses={
        **_PENDIENTE,
        **_NO_EXISTE,
        409: _error(409, "CUENTA_EN_USO: la cuenta tiene movimientos o subcuentas."),
        **_NO_HABILITADA,
    },
    openapi_extra={"x-roles": _ROLES_ESCRITURA_CUENTAS},
)
def eliminar_cuenta_contable(conn: Db, id_cuenta: IdCuentaContable) -> Response:
    """Elimina la cuenta: 204, o 202 si queda pendiente de aprobación."""
    service.eliminar_cuenta_contable(conn, id_cuenta)
    return Response(status_code=204)


router.include_router(_cuentas_escritura_router)


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

router.include_router(importaciones.router)

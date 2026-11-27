from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, UsuarioActual, require_auth, require_roles
from app.core.security.operador import IdInterno, auditar, exigir_id_interno
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.auth.agencias import agencia_consulta_asientos
from app.modules.contabilidad import corte_workos, importaciones, service
from app.modules.contabilidad.schemas import (
    INT32_MAX,
    Asiento,
    AsientoManual,
    AsientoManualCreado,
    CuentaContable,
    CuentaContableCrear,
    CuentaContableEditar,
    CuentaContableEstado,
    FechaContable,
    MotivoAsientoManual,
    PageAsiento,
)
from app.modules.parametros.funciones import funcion_pendiente

from .cuentas_producto_api import router as cuentas_producto_router
from .plantillas import router as plantillas_router

router = APIRouter(
    prefix="/contabilidad",
    tags=["contabilidad"],
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]

router.include_router(plantillas_router)
router.include_router(cuentas_producto_router)

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
# #206: alta, edicion y estado funcionales; baja pendiente con contrato E0-09.
# ---------------------------------------------------------------------------
# Roles: solo CONTADOR. El AUDITOR (y el ADMIN) solo leen el plan con CON-03.
_ROLES_ESCRITURA_CUENTAS = ["CONTADOR"]
_cuentas_escritura_router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[
        Depends(require_roles("CONTADOR")),
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
    404: {
        "description": "FUNCION_NO_DISPONIBLE: funcion pendiente.",
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
        409: _error(
            409,
            "CODIGO_DUPLICADO: ya existe una cuenta con ese código. "
            "CUENTA_SUPERIOR_CON_MOVIMIENTOS: el padre es imputable y tiene "
            "movimientos o saldo; si no los tiene, se marca como no imputable.",
        ),
        422: _error(
            422,
            "CODIGO_NO_CORRESPONDE_AL_PADRE: el código no empieza con el del padre.",
        ),
        **_NO_HABILITADA,
    },
    openapi_extra={"x-roles": _ROLES_ESCRITURA_CUENTAS},
)
def crear_cuenta_contable(
    conn: Db, datos: CuentaContableCrear, request: Request, usuario: UsuarioActual
) -> Any:
    """Alta de una cuenta del plan: 201 con la cuenta o 202 si queda pendiente."""
    return service.crear_cuenta_contable(
        conn, usuario, ip_cliente(request.scope), datos
    )


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
    conn: Db,
    id_cuenta: IdCuentaContable,
    datos: CuentaContableEstado,
    request: Request,
    usuario: UsuarioActual,
) -> Any:
    """Activa o desactiva la cuenta: 200 con la cuenta o 202 si queda pendiente."""
    return service.cambiar_estado_cuenta_contable(
        conn, usuario, ip_cliente(request.scope), id_cuenta, datos
    )


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
def eliminar_cuenta_contable(
    conn: Db, id_cuenta: IdCuentaContable, usuario: UsuarioActual
) -> Response:
    """Elimina la cuenta: 204, o 202 si queda pendiente de aprobación."""
    with funcion_pendiente("FUNCION_CONTABILIDAD_BAJA_CUENTA", conn, usuario):
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
    usuario: Annotated[Usuario, Depends(require_auth)],
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
        id_agencia=agencia_consulta_asientos(usuario, id_agencia),
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
    usuario: Annotated[Usuario, Depends(require_auth)],
    id_asiento: Annotated[int, Path(alias="idAsiento", ge=1, le=INT32_MAX)],
) -> Any:
    """CON-05 · Asiento con su detalle (líneas ordenadas por IdMovimientoContable)."""
    resultado = service.obtener_asiento(conn, id_asiento)
    agencia_consulta_asientos(usuario, resultado["id_agencia"])
    return resultado


router.include_router(_asientos_router)


# ---------------------------------------------------------------------------
# E4-04 (#383) · Asientos manuales con aprobación y reverso: contrato pendiente
# ---------------------------------------------------------------------------
# Roles: solo CONTADOR escribe. El AUDITOR y el ADMIN consultan con CON-04/05.
# La aprobación se resuelve en /aprobaciones (E0-08) y la hace otra persona.
# Ramas pendientes de E0-09: el servicio lanza el 501 interno y funcion_pendiente lo
# cierra con 404 FUNCION_NO_DISPONIBLE (las claves aún no tienen semilla: apagadas).
_ROLES_ASIENTOS_MANUALES = ["CONTADOR"]
_asientos_manuales_router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[
        Depends(require_roles(*_ROLES_ASIENTOS_MANUALES)),
        Depends(solo_parametros()),
    ],
)
IdAsiento = Annotated[int, Path(alias="idAsiento", ge=1, le=INT32_MAX)]

_CLAVE_ASIENTO_MANUAL = "FUNCION_CONTABILIDAD_ASIENTO_MANUAL"
_CLAVE_REVERSO_ASIENTO = "FUNCION_CONTABILIDAD_REVERSO_ASIENTO"
_FUNCION_PENDIENTE = "FUNCION_NO_DISPONIBLE: función pendiente (E0-09)."
# Una sola entrada 404 por ruta: si se combinan dos dicts con 404, el último pisa.
_FUNCION_NO_DISPONIBLE = {404: _error(404, _FUNCION_PENDIENTE)}
_ASIENTO_NO_EXISTE = {
    404: _error(
        404, f"ASIENTO_NO_ENCONTRADO: el asiento no existe. {_FUNCION_PENDIENTE}"
    )
}
_NO_EDITABLE = (
    "ASIENTO_NO_EDITABLE: el asiento no está en BORRADOR (ya se envió, se "
    "contabilizó o se anuló)."
)
_SIN_PERMISO_Y_AUTOAPROBACION = _error(
    403,
    "SIN_PERMISO: el rol no es CONTADOR. La aprobación la resuelve otra persona en "
    "POST /aprobaciones/{idSolicitud}/aprobar: quien envió el asiento recibe 403 "
    "APROBADOR_ES_SOLICITANTE si intenta aprobarlo.",
)
_PENDIENTE_APROBACION = {
    "model": SolicitudAceptada,
    "description": "Pendiente de aprobación en E0-08 (/aprobaciones).",
}


@_asientos_manuales_router.post(
    "/asientos",
    operation_id="E404Crear",
    status_code=201,
    response_model=AsientoManualCreado,
    responses={**_FUNCION_NO_DISPONIBLE},
    openapi_extra={"x-roles": _ROLES_ASIENTOS_MANUALES},
)
def crear_asiento_manual(conn: Db, datos: AsientoManual, usuario: UsuarioActual) -> Any:
    """Asiento manual en BORRADOR; puede guardarse incompleto o sin cuadrar.

    Las reglas contables (al menos dos líneas, débitos = créditos, cuentas
    habilitadas, período abierto) se validan al enviarlo.
    """
    with funcion_pendiente(_CLAVE_ASIENTO_MANUAL, conn, usuario):
        return service.crear_asiento_manual(conn, datos)


@_asientos_manuales_router.put(
    "/asientos/{idAsiento}",
    operation_id="E404Editar",
    response_model=Asiento,
    responses={
        **_ASIENTO_NO_EXISTE,
        409: _error(409, _NO_EDITABLE),
    },
    openapi_extra={"x-roles": _ROLES_ASIENTOS_MANUALES},
)
def editar_asiento_manual(
    conn: Db, id_asiento: IdAsiento, datos: AsientoManual, usuario: UsuarioActual
) -> Any:
    """Reemplaza el borrador completo (cabecera y líneas); 200 con el asiento."""
    with funcion_pendiente(_CLAVE_ASIENTO_MANUAL, conn, usuario):
        return service.editar_asiento_manual(conn, id_asiento, datos)


@_asientos_manuales_router.post(
    "/asientos/{idAsiento}/envio",
    operation_id="E404Envio",
    status_code=202,
    response_model=SolicitudAceptada,
    responses={
        202: _PENDIENTE_APROBACION,
        403: _SIN_PERMISO_Y_AUTOAPROBACION,
        **_ASIENTO_NO_EXISTE,
        409: _error(
            409,
            f"{_NO_EDITABLE} CUENTA_CONTABLE_NO_HABILITADA: una cuenta está "
            "inactiva, no es imputable o tiene subcuentas. "
            "PERIODO_CONTABLE_NO_ABIERTO: el día o el mes contable no están abiertos.",
        ),
        422: _error(
            422,
            "ASIENTO_NO_CUADRA: tiene menos de dos líneas o los débitos no suman lo "
            "mismo que los créditos. CUENTA_SOLO_AUTOMATICA: una cuenta solo admite "
            "asientos automáticos.",
        ),
    },
    openapi_extra={"x-roles": _ROLES_ASIENTOS_MANUALES},
)
def enviar_asiento_manual(
    conn: Db, id_asiento: IdAsiento, usuario: UsuarioActual
) -> Any:
    """Valida el borrador y lo deja PENDIENTE_APROBACION; 202 con la solicitud."""
    with funcion_pendiente(_CLAVE_ASIENTO_MANUAL, conn, usuario):
        return service.enviar_asiento_manual(conn, id_asiento)


@_asientos_manuales_router.post(
    "/asientos/{idAsiento}/anulacion",
    operation_id="E404Anulacion",
    response_model=Asiento,
    responses={
        **_ASIENTO_NO_EXISTE,
        409: _error(409, _NO_EDITABLE),
    },
    openapi_extra={"x-roles": _ROLES_ASIENTOS_MANUALES},
)
def anular_asiento_manual(
    conn: Db, id_asiento: IdAsiento, datos: MotivoAsientoManual, usuario: UsuarioActual
) -> Any:
    """Anula un borrador (queda ANULADO); 200 con el asiento."""
    with funcion_pendiente(_CLAVE_ASIENTO_MANUAL, conn, usuario):
        return service.anular_asiento_manual(conn, id_asiento, datos)


@_asientos_manuales_router.post(
    "/asientos/{idAsiento}/reverso",
    operation_id="CON06Reverso",
    status_code=202,
    response_model=SolicitudAceptada,
    responses={
        202: _PENDIENTE_APROBACION,
        403: _SIN_PERMISO_Y_AUTOAPROBACION,
        **_ASIENTO_NO_EXISTE,
        409: _error(
            409,
            "ASIENTO_DE_OPERACION: el asiento no es manual; se reversa desde la "
            "operación de origen. ASIENTO_YA_REVERSADO: ya tiene reverso. "
            "ASIENTO_NO_REVERSABLE: no es un original CONTABILIZADO. "
            "PERIODO_CONTABLE_NO_ABIERTO. CUENTA_CONTABLE_NO_HABILITADA.",
        ),
    },
    openapi_extra={"x-roles": _ROLES_ASIENTOS_MANUALES},
)
def reversar_asiento_manual(
    conn: Db, id_asiento: IdAsiento, datos: MotivoAsientoManual, usuario: UsuarioActual
) -> Any:
    """CON-06 · Pide el reverso de un asiento manual contabilizado; 202."""
    with funcion_pendiente(_CLAVE_REVERSO_ASIENTO, conn, usuario):
        return service.reversar_asiento_manual(conn, id_asiento, datos)


router.include_router(_asientos_manuales_router)

router.include_router(importaciones.router)
router.include_router(corte_workos.router)

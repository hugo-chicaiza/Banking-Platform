from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.core import csv as csv_tool
from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, problema
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import (
    Usuario,
    UsuarioAuditoria,
    require_auth,
    require_roles,
)
from app.modules.aprobaciones import router as aprobaciones
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.clientes import correos, revelacion, service
from app.modules.clientes.aprobacion import CODIGO_EDICION, objetivo
from app.modules.clientes.aprobacion_estado import (
    CODIGO_ESTADO,
)
from app.modules.clientes.aprobacion_estado import (
    objetivo as objetivo_estado,
)
from app.modules.clientes.aprobacion_riesgo import (
    CODIGO_RIESGO,
)
from app.modules.clientes.aprobacion_riesgo import (
    objetivo as objetivo_riesgo,
)
from app.modules.clientes.habilitacion import HabilitacionCliente, cliente_habilitado
from app.modules.clientes.schemas import (
    Cliente,
    ClienteBusqueda,
    ClienteCreate,
    ClienteEstadoUpdate,
    ClientePerfil,
    ClienteUpdate,
    DesafioRevelacion,
    Direccion,
    DireccionNueva,
    DireccionUpdate,
    PageCliente,
    PageClienteHistorial,
    Revelacion,
    Riesgo,
    RiesgoCreate,
    RiesgoRegistrado,
    SolicitudDesafio,
    SolicitudRevelacion,
    TipoDocumento,
    ValidacionIdentificacion,
)
from app.modules.clientes.visibilidad import aplicar_visibilidad, puede_ver_direcciones
from app.modules.parametros.service import hoy


def _sin_cache(response: Response) -> None:
    """Datos personales: ningún intermediario ni navegador los guarda (ASVS 14.3.2)."""
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    tags=["clientes"],
    dependencies=[Depends(require_auth), Depends(_sin_cache)],
)
_ROLES_EXPORTACION = ["SUPERVISOR", "ADMIN"]
_gestion_router = APIRouter(route_class=ProblemDetailsRoute, responses=RESPUESTAS_ERROR)

Db = Annotated[Connection, Depends(cooperativa)]

# Roles de cada tarea (GitHubProject_Files): 403 SIN_PERMISO si no tiene ninguno
_ASESOR_ADMIN = [Depends(require_roles("ASESOR", "ADMIN"))]
_EDITAR_CLIENTE = [Depends(require_roles("ASESOR", "ADMIN"))]

_consultas_router = APIRouter(route_class=ProblemDetailsRoute)
_ROLES_CONSULTA = ["ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"]


@_consultas_router.post(
    "/busqueda",
    operation_id="CLI03",
    response_model=PageCliente,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles(*_ROLES_CONSULTA))],
    openapi_extra={"x-roles": _ROLES_CONSULTA},
)
def buscar_clientes(
    filtros: ClienteBusqueda,
    conn: Db,
    usuario: Annotated[Usuario, Depends(require_auth)],
) -> PageCliente:
    """E5-05 · filtros en el cuerpo (no en la URL); siempre con filtro y paginada."""
    return aplicar_visibilidad(service.listar_clientes(conn, filtros), usuario)


_COLUMNAS_EXPORTACION = (
    "idCliente",
    "identificacion",
    "tipoCliente",
    "nombres",
    "apellidos",
    "razonSocial",
    "estado",
    "idAgenciaRegistro",
    "email",
    "telefonoCelular",
)
MAX_FILAS_EXPORTACION = 5000


@_consultas_router.post(
    "/busqueda/exportacion",
    operation_id="CLIExportar",
    responses={**RESPUESTAS_ERROR, **csv_tool.RESPUESTA_CSV},
    response_class=Response,
    dependencies=[Depends(require_roles(*_ROLES_EXPORTACION))],
    openapi_extra={"x-roles": _ROLES_EXPORTACION, "x-permissions": ["org-exportar"]},
)
def exportar_clientes(
    filtros: ClienteBusqueda,
    request: Request,
    conn: Db,
    usuario: Annotated[Usuario, Depends(require_auth)],
) -> Response:
    """CSV del resultado de la búsqueda, enmascarado y auditado (CLI_EXPORTACION)."""
    csv_tool.autorizar(usuario)
    filas: list[list[Any]] = []
    pagina = filtros.model_copy(update={"page_size": 100})
    for numero in range(1, MAX_FILAS_EXPORTACION // 100 + 1):
        resultado = aplicar_visibilidad(
            service.listar_clientes(conn, pagina.model_copy(update={"page": numero})),
            usuario,
            permitido=False,
        )
        filas.extend(
            [
                c.id_cliente,
                c.identificacion,
                c.tipo_cliente,
                c.nombres,
                c.apellidos,
                c.razon_social,
                c.estado,
                c.id_agencia_registro,
                c.email,
                c.telefono_celular,
            ]
            for c in resultado.items
        )
        if numero * 100 >= resultado.total:
            break
    return csv_tool.responder_csv(
        usuario,
        ip_cliente(request.scope),
        "clientes",
        "Clientes.Cliente",
        _COLUMNAS_EXPORTACION,
        filas[:MAX_FILAS_EXPORTACION],
        evento="CLI_EXPORTACION",
    )


@_consultas_router.get(
    "/{idCliente}",
    operation_id="CLI04",
    response_model=Cliente,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles(*_ROLES_CONSULTA))],
    openapi_extra={"x-roles": _ROLES_CONSULTA},
)
def obtener_cliente(
    idCliente: int, conn: Db, usuario: Annotated[Usuario, Depends(require_auth)]
) -> Cliente:
    """Detalle del cliente con sus direcciones activas (CLI-04 / C-03)."""
    return aplicar_visibilidad(service.obtener_cliente(conn, idCliente), usuario)


@_consultas_router.get(
    "/{idCliente}/perfil",
    operation_id="CLI08",
    response_model=ClientePerfil,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles("ASESOR", "SUPERVISOR", "ADMIN"))],
    openapi_extra={"x-roles": ["ASESOR", "SUPERVISOR", "ADMIN"]},
)
def obtener_perfil_cliente(
    idCliente: int, conn: Db, usuario: Annotated[Usuario, Depends(require_auth)]
) -> ClientePerfil:
    """Datos generales, riesgo vigente y productos financieros (CLI-08 / C-06)."""
    return aplicar_visibilidad(service.obtener_perfil_cliente(conn, idCliente), usuario)


# ---------------------------------------------------------------------------
# GET /api/v1/clientes/validar-identificacion
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.get(
    "/validar-identificacion",
    operation_id="CLI01",
    response_model=ValidacionIdentificacion,
    dependencies=_ASESOR_ADMIN,
)
def validar_identificacion(
    tipo_documento: Annotated[
        TipoDocumento,
        Query(
            description="Tipo de documento: C (Cédula), R (RUC), P (Pasaporte)",
            alias="tipoDocumento",
        ),
    ],
    identificacion: Annotated[
        str,
        Query(
            description="Número de documento de identificación",
            min_length=1,
            max_length=20,
        ),
    ],
    conn: Db,
) -> Any:
    """Valida formato del documento (Módulo 10 para Cédula/RUC) y si ya existe (CLI-01 / C-02)."""
    return service.validar_identificacion(conn, tipo_documento, identificacion)


# ---------------------------------------------------------------------------
# POST /api/v1/clientes
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.post(
    "",
    operation_id="CLI02",
    response_model=Cliente,
    status_code=201,
    dependencies=_EDITAR_CLIENTE,
)
def registrar_cliente(
    payload: ClienteCreate,
    request: Request,
    creado_por: UsuarioAuditoria,
    conn: Db,
    usuario: Annotated[Usuario, Depends(require_auth)],
) -> Any:
    """Registra un cliente (Natural o Jurídico) con su dirección principal (CLI-02 / C-01).

    `creado_por` es el usuario de la sesión, vinculado por Organizacion.Usuarios.KeyUsuario.
    """
    # Obtener IP del cliente para auditoría en ClientesHis
    direccion_ip = _ip_cliente(request)
    visibles = puede_ver_direcciones(usuario)

    return aplicar_visibilidad(
        service.registrar_cliente(
            conn, payload, creado_por, direccion_ip, usuario.agencia()
        ),
        usuario,
        permitido=visibles,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/clientes/{idCliente}/direcciones
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.get(
    "/{idCliente}/direcciones",
    operation_id="CLI09",
    response_model=list[Direccion],
    dependencies=_ASESOR_ADMIN,
)
def listar_direcciones(
    idCliente: int,
    conn: Db,
) -> Any:
    """Retorna las direcciones activas e inactivas del cliente (CLI-09 / C-07)."""
    return service.listar_direcciones(conn, idCliente)


# ---------------------------------------------------------------------------
# POST /api/v1/clientes/{idCliente}/direcciones
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.post(
    "/{idCliente}/direcciones",
    operation_id="CLI10",
    response_model=Direccion,
    status_code=201,
    dependencies=_EDITAR_CLIENTE,
)
def agregar_direccion(
    idCliente: int,
    payload: DireccionNueva,
    request: Request,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Any:
    """Agrega una nueva dirección al cliente (CLI-10 / C-07)."""
    direccion_ip = _ip_cliente(request)
    return service.agregar_direccion(
        conn, idCliente, payload, modificado_por, direccion_ip
    )


# ---------------------------------------------------------------------------
# PATCH /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.patch(
    "/{idCliente}/direcciones/{idDireccion}",
    operation_id="CLI11",
    response_model=Direccion,
    dependencies=_EDITAR_CLIENTE,
)
def editar_direccion(
    idCliente: int,
    idDireccion: int,
    payload: DireccionUpdate,
    request: Request,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Any:
    """Edita una dirección o la promueve a principal."""
    direccion_ip = _ip_cliente(request)
    return service.editar_direccion(
        conn, idCliente, idDireccion, payload, modificado_por, direccion_ip
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN


@_gestion_router.delete(
    "/{idCliente}/direcciones/{idDireccion}",
    operation_id="CLI12",
    status_code=204,
    dependencies=_EDITAR_CLIENTE,
)
def eliminar_direccion(
    idCliente: int,
    idDireccion: int,
    request: Request,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Response:
    """Baja lógica de una dirección (CLI-12 / C-07)."""
    service.eliminar_direccion(
        conn, idCliente, idDireccion, modificado_por, _ip_cliente(request)
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Helpers internos del router
# ---------------------------------------------------------------------------


def _ip_cliente(request: Request) -> str:
    """IP confiable del usuario: X-Forwarded-For no se lee porque el cliente puede
    falsificarlo (ASVS 4.1.3); ip_cliente solo acepta la que fija el Worker."""
    return ip_cliente(request.scope)


_riesgo_router = APIRouter(route_class=ProblemDetailsRoute)


def _solicitar_riesgo(
    request: Request, usuario: Usuario, id_cliente: int
) -> service.SolicitarRiesgo:
    def solicitar(contenido: dict[str, Any]) -> SolicitudAceptada:
        actor = aprobaciones.actual(usuario)
        try:
            id_solicitud = aprobaciones.servicio().solicitar(
                actor,
                CODIGO_RIESGO,
                objetivo_riesgo(id_cliente),
                contenido,
                hoy(),
                aprobaciones.contexto(request, usuario),
            )
        except HTTPException as error:
            detalle: Any = error.detail
            if (
                isinstance(detalle, dict)
                and detalle.get("code") == "SOLICITUD_YA_PENDIENTE"
            ):
                raise problema(
                    409,
                    "EVALUACION_PENDIENTE",
                    "El cliente ya tiene una evaluación de riesgo pendiente de aprobación.",
                ) from None
            raise
        return SolicitudAceptada(id_solicitud=id_solicitud)

    return solicitar


@_riesgo_router.post(
    "/{idCliente}/evaluaciones-riesgo",
    operation_id="CLI13",
    response_model=RiesgoRegistrado,
    status_code=201,
    responses={
        **RESPUESTAS_ERROR,
        202: {
            "model": SolicitudAceptada,
            "description": "Evaluación con PEP, riesgo Alto o Rechazada enviada a aprobación de otra persona.",
        },
        409: {
            **RESPUESTAS_ERROR[500],
            "description": "Evaluación pendiente de aprobación",
        },
        422: {**RESPUESTAS_ERROR[500], "description": "Datos de evaluación inválidos"},
    },
    dependencies=[Depends(require_roles("ASESOR", "SUPERVISOR", "ADMIN"))],
    openapi_extra={"x-roles": ["ASESOR", "SUPERVISOR", "ADMIN"]},
)
def registrar_evaluacion_riesgo(
    idCliente: int,
    payload: RiesgoCreate,
    request: Request,
    response: Response,
    usuario: Annotated[Usuario, Depends(require_auth)],
    evaluador: UsuarioAuditoria,
    conn: Db,
) -> RiesgoRegistrado | Response:
    """Registra riesgo y devuelve el estado posterior al trigger (CLI-13 / C-08)."""
    resultado = service.registrar_evaluacion_riesgo(
        conn,
        idCliente,
        payload,
        evaluador,
        _ip_cliente(request),
        solicitar=_solicitar_riesgo(request, usuario, idCliente),
    )
    if isinstance(resultado, SolicitudAceptada):
        return JSONResponse(
            resultado.model_dump(mode="json", by_alias=True),
            status_code=202,
            headers=dict(response.headers),
        )
    return resultado


@_riesgo_router.get(
    "/{idCliente}/evaluaciones-riesgo",
    operation_id="CLI14",
    response_model=list[Riesgo],
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles("ASESOR", "SUPERVISOR", "AUDITOR", "ADMIN"))],
    openapi_extra={"x-roles": ["ASESOR", "SUPERVISOR", "AUDITOR", "ADMIN"]},
)
def listar_evaluaciones_riesgo(idCliente: int, conn: Db) -> list[Riesgo]:
    """Historial de evaluaciones por fecha e identificador descendentes (CLI-14)."""
    return service.listar_evaluaciones_riesgo(conn, idCliente)


@_riesgo_router.get(
    "/{idCliente}/habilitacion",
    operation_id="CLIHabilitacionProducto",
    response_model=HabilitacionCliente,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_roles("ASESOR", "SUPERVISOR", "AUDITOR", "ADMIN"))],
    openapi_extra={"x-roles": ["ASESOR", "SUPERVISOR", "AUDITOR", "ADMIN"]},
)
def consultar_habilitacion(idCliente: int, conn: Db) -> HabilitacionCliente:
    return cliente_habilitado(conn, idCliente, hoy())


_edicion_router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses={
        **RESPUESTAS_ERROR,
        503: {**RESPUESTAS_ERROR[500], "description": "Service Unavailable"},
    },
)
EditorCliente = Annotated[Usuario, Depends(require_roles("ASESOR", "ADMIN"))]
GestorEstado = Annotated[
    Usuario, Depends(require_roles("ASESOR", "SUPERVISOR", "ADMIN"))
]
LectorHistorial = Annotated[
    Usuario, Depends(require_roles("SUPERVISOR", "AUDITOR", "ADMIN"))
]


def _solicitar_cambio(
    request: Request, usuario: Usuario, id_cliente: int
) -> service.SolicitarCambio:
    def solicitar(contenido: dict[str, Any]) -> SolicitudAceptada:
        actor = aprobaciones.actual(usuario)
        try:
            id_solicitud = aprobaciones.servicio().solicitar(
                actor,
                CODIGO_EDICION,
                objetivo(id_cliente),
                contenido,
                hoy(),
                aprobaciones.contexto(request, usuario),
            )
        except HTTPException as error:
            detalle: Any = error.detail
            if (
                isinstance(detalle, dict)
                and detalle.get("code") == "SOLICITUD_YA_PENDIENTE"
            ):
                raise problema(
                    409,
                    "CAMBIO_PENDIENTE",
                    "El cliente ya tiene un cambio sensible pendiente de aprobación.",
                ) from None
            raise
        return SolicitudAceptada(id_solicitud=id_solicitud)

    return solicitar


@_edicion_router.patch(
    "/{idCliente}",
    operation_id="CLI05",
    response_model=Cliente,
    responses={
        202: {
            "model": SolicitudAceptada,
            "description": "Cambio sensible enviado a aprobación de otra persona.",
        },
        423: {**RESPUESTAS_ERROR[500], "description": "Cliente bloqueado"},
    },
    openapi_extra={"x-roles": ["ASESOR", "ADMIN"]},
)
def editar_cliente(
    idCliente: int,
    payload: ClienteUpdate,
    request: Request,
    response: Response,
    usuario: EditorCliente,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Cliente | Response:
    """Datos ordinarios al instante (200); nombres, documento, fecha de nacimiento y
    correo principal quedan pendientes de la aprobación de otra persona (202)."""
    visibles = puede_ver_direcciones(usuario)
    resultado = service.editar_cliente(
        conn,
        idCliente,
        payload,
        modificado_por,
        ip_cliente(request.scope),
        _solicitar_cambio(request, usuario, idCliente),
    )
    if isinstance(resultado, SolicitudAceptada):
        return JSONResponse(
            resultado.model_dump(mode="json", by_alias=True),
            status_code=202,
            headers=dict(response.headers),
        )
    return aplicar_visibilidad(resultado, usuario, permitido=visibles)


def _solicitar_estado(
    request: Request, usuario: Usuario, id_cliente: int
) -> service.SolicitarEstado:
    def solicitar(contenido: dict[str, Any]) -> SolicitudAceptada:
        actor = aprobaciones.actual(usuario)
        try:
            id_solicitud = aprobaciones.servicio().solicitar(
                actor,
                CODIGO_ESTADO,
                objetivo_estado(id_cliente),
                contenido,
                hoy(),
                aprobaciones.contexto(request, usuario),
            )
        except HTTPException as error:
            detalle: Any = error.detail
            if (
                isinstance(detalle, dict)
                and detalle.get("code") == "SOLICITUD_YA_PENDIENTE"
            ):
                raise problema(
                    409,
                    "CAMBIO_ESTADO_PENDIENTE",
                    "El cliente ya tiene un cambio de estado pendiente de aprobación.",
                ) from None
            raise
        return SolicitudAceptada(id_solicitud=id_solicitud)

    return solicitar


@_edicion_router.patch(
    "/{idCliente}/estado",
    operation_id="CLI06",
    response_model=Cliente,
    responses={
        **RESPUESTAS_ERROR,
        202: {
            "model": SolicitudAceptada,
            "description": "Cambio de estado enviado a aprobación de otra persona.",
        },
        409: {
            **RESPUESTAS_ERROR[500],
            "description": "Cambio de estado pendiente o conflicto de transición",
        },
        422: {
            **RESPUESTAS_ERROR[500],
            "description": "Datos de cambio de estado inválidos",
        },
    },
    openapi_extra={"x-roles": ["ASESOR", "SUPERVISOR", "ADMIN"]},
)
def cambiar_estado_cliente(
    idCliente: int,
    payload: ClienteEstadoUpdate,
    request: Request,
    response: Response,
    usuario: GestorEstado,
    modificado_por: UsuarioAuditoria,
    conn: Db,
) -> Cliente | Response:
    """Transición explícita, con comprobación de productos para la baja."""
    from app.modules.seguridad import funciones

    autorizacion = (
        {"funcion_autorizada": True}
        if funciones.autorizar_operacion(request, usuario)
        else {}
    )
    visibles = puede_ver_direcciones(usuario)
    resultado = service.cambiar_estado_cliente(
        conn,
        idCliente,
        payload,
        modificado_por,
        ip_cliente(request.scope),
        usuario.roles,
        solicitar=_solicitar_estado(request, usuario, idCliente),
        **autorizacion,
    )
    if isinstance(resultado, SolicitudAceptada):
        return JSONResponse(
            resultado.model_dump(mode="json", by_alias=True),
            status_code=202,
            headers=dict(response.headers),
        )
    return aplicar_visibilidad(resultado, usuario, permitido=visibles)


@_edicion_router.get(
    "/{idCliente}/historial",
    operation_id="CLI07",
    response_model=PageClienteHistorial,
    openapi_extra={"x-roles": ["SUPERVISOR", "AUDITOR", "ADMIN"]},
)
def listar_historial_cliente(
    idCliente: int,
    usuario: LectorHistorial,
    conn: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: str | None = None,
) -> PageClienteHistorial:
    """Historial inmutable; exige una sesión válida de WorkOS y el rol indicado."""
    return service.listar_historial_cliente(
        conn, idCliente, page=page, page_size=page_size, sort=sort
    )


_ROLES_REVELACION = ["ASESOR", "SUPERVISOR", "ADMIN"]
_revelacion_router = APIRouter(
    route_class=ProblemDetailsRoute, responses=RESPUESTAS_ERROR
)
Revelador = Annotated[Usuario, Depends(require_roles(*_ROLES_REVELACION))]


@_revelacion_router.post(
    "/{idCliente}/revelacion/desafio",
    operation_id="CLIRevelacionDesafio",
    response_model=DesafioRevelacion,
    openapi_extra={"x-roles": _ROLES_REVELACION},
)
def pedir_desafio(
    idCliente: int, solicitud: SolicitudDesafio, usuario: Revelador, conn: Db
) -> DesafioRevelacion:
    """Segundo factor para mostrar ESTOS campos de ESTE cliente (no sirve para otros)."""
    return revelacion.desafiar(conn, idCliente, usuario, solicitud.campos)


@_revelacion_router.post(
    "/{idCliente}/revelacion",
    operation_id="CLIRevelacion",
    response_model=Revelacion,
    openapi_extra={"x-roles": _ROLES_REVELACION},
)
def revelar_datos(
    idCliente: int,
    solicitud: SolicitudRevelacion,
    request: Request,
    usuario: Revelador,
    id_interno: UsuarioAuditoria,
    conn: Db,
) -> Revelacion:
    """Valor completo de los campos pedidos tras verificar el código; auditado."""
    return revelacion.revelar(
        conn, idCliente, solicitud, usuario, id_interno, ip_cliente(request.scope)
    )


router.include_router(_gestion_router, prefix="/clientes")
router.include_router(_edicion_router, prefix="/clientes")
router.include_router(_riesgo_router, prefix="/clientes")
router.include_router(_consultas_router, prefix="/clientes")
router.include_router(_revelacion_router, prefix="/clientes")
router.include_router(correos.router, prefix="/clientes")

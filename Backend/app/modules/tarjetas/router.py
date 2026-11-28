import json
import re
from collections.abc import Iterator
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import SecretStr
from sqlalchemy import Connection

from app.core.api.errors import (
    RESPUESTAS_ERROR,
    ProblemDetailsRoute,
    problema,
    solo_parametros,
)
from app.core.api.middleware import ip_cliente
from app.core.config.settings import get_settings
from app.core.database.db import cooperativa, get_engine
from app.core.pdf import respuesta_pdf, respuestas_pdf
from app.core.security.auth import (
    UsuarioActual,
    UsuarioAuditoria,
    require_auth,
    require_roles,
)
from app.modules.aprobaciones import router as aprobaciones
from app.modules.seguridad.funciones_catalogo import POR_ID
from app.modules.tarjetas import accesos, aprobacion, service
from app.modules.tarjetas.schemas import (
    MAX_INT,
    MAX_PAGE_SIZE,
    MAX_PAGINA,
    EnvioTarjeta,
    EnvioTarjetaUpdate,
    EstadoTarjeta,
    PageTarjeta,
    PageTarjetaHistorial,
    PageTarjetaPorRenovar,
    PinBlockPrueba,
    PinBlockPruebaEntrada,
    Tarjeta,
    TarjetaCreate,
    TarjetaEstadoUpdate,
)

_MAX_BODY_PIN = 1024


def _sin_cache(response: Response) -> None:
    """Evita que navegadores o proxies guarden datos de tarjeta."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(
    prefix="/tarjetas",
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    tags=["tarjetas"],
    dependencies=[Depends(require_auth), Depends(_sin_cache)],
)

Db = Annotated[Connection, Depends(cooperativa)]
IdTarjetaPath = Annotated[int, Path(alias="idTarjeta", gt=0, le=MAX_INT)]
Page = Annotated[int, Query(ge=1, le=MAX_PAGINA)]
PageSize = Annotated[int, Query(alias="pageSize", ge=1, le=MAX_PAGE_SIZE)]
Sort = Annotated[
    str | None, Query(max_length=30, description="Campo,asc/desc de la lista permitida")
]


def seguridad() -> Iterator[Connection]:
    """Conexión a SeguridadDB: PIN Offset y repositorio de PAN ficticios."""
    with get_engine("seguridad").connect() as conn:
        yield conn


async def _leer_json(request: Request, error: Exception) -> dict[str, Any]:
    """Lee el body a mano, con tope de tamaño. Nunca repite lo recibido."""
    contenido = bytearray()
    async for parte in request.stream():
        contenido += parte
        if len(contenido) > _MAX_BODY_PIN:
            raise error
    try:
        datos = json.loads(contenido)
    except ValueError:
        raise error from None
    if not isinstance(datos, dict):
        raise error
    return datos


async def _sin_body(request: Request) -> None:
    """TAR-05 no lleva body: el PIN lo genera el HSM, nunca lo envía el cliente."""
    async for parte in request.stream():
        if parte:
            raise problema(400, "DATOS_INVALIDOS", "La solicitud no admite cuerpo.")


async def _leer_pin_prueba(request: Request) -> tuple[int, SecretStr]:
    """PIN pad simulado: lee {idTarjeta, pin} sin repetir el PIN en los errores."""
    error = problema(400, "PIN_INVALIDO", "Envíe idTarjeta y un PIN de 4 dígitos.")
    datos = await _leer_json(request, error)
    if set(datos) != {"idTarjeta", "pin"}:
        raise error
    id_tarjeta, pin = datos["idTarjeta"], datos["pin"]
    if (
        type(id_tarjeta) is not int
        or not 0 < id_tarjeta <= MAX_INT
        or not isinstance(pin, str)
        or not re.fullmatch(r"[0-9]{4}", pin)
    ):
        raise error
    return id_tarjeta, SecretStr(pin)


def _ip(request: Request) -> str | None:
    # La IP confiable la resuelve ip_cliente (solo del Worker con el secreto)
    return ip_cliente(request.scope)


def _agencia_operativa(operador: UsuarioActual) -> str:
    agencia = operador.agencia()
    if not agencia:
        raise problema(
            403,
            "AGENCIA_REQUERIDA",
            "Seleccione una agencia operativa para continuar.",
        )
    return agencia


# TAR-01. Roles: ASESOR, ADMIN
@router.post(
    "",
    response_model=Tarjeta,
    status_code=201,
    dependencies=[Depends(require_roles(*POR_ID["tarjetas.emitir"].roles_iniciales))],
)
def emitir_tarjeta(
    payload: TarjetaCreate,
    request: Request,
    agencia: Annotated[str, Depends(_agencia_operativa)],
    operador: UsuarioActual,
    usuario: UsuarioAuditoria,
    actor: aprobaciones.Actual,
    cola: aprobaciones.Cola,
    conn: Db,
    conn_seguridad: Annotated[Connection, Depends(seguridad)],
) -> Any:
    """Registra una tarjeta Solicitada para su aprobación por otro operador.

    Requiere confirmar la agencia operativa de la cuenta. Si la publicación en la
    cola se difiere, la respuesta devuelve idSolicitudAprobacion nulo y la recupera el ejecutor.
    """
    if usuario != actor.id_interno:
        raise problema(403, "ACTOR_NO_ACTIVO", "No se pudo acreditar al solicitante.")
    actor.alcance(agencia)

    def registrar(conexion: Connection, id_tarjeta: int) -> None:
        aprobacion.programar(conexion, id_tarjeta, actor, agencia)

    tarjeta = service.crear_tarjeta(
        conn,
        conn_seguridad,
        payload,
        usuario,
        _ip(request),
        registrar_solicitud=registrar,
    )
    tarjeta.id_solicitud_aprobacion = aprobacion.publicar_al_solicitar(
        cola, tarjeta.id_tarjeta, aprobaciones.contexto(request, operador)
    )
    return tarjeta


# TAR-02. Roles: ASESOR, SUPERVISOR, ADMIN
@router.get(
    "",
    response_model=PageTarjeta,
    dependencies=[
        Depends(require_roles(*POR_ID["tarjetas.consultar"].roles_iniciales)),
        Depends(
            solo_parametros(
                "idCliente",
                "idCuenta",
                "estado",
                "esExtension",
                "page",
                "pageSize",
                "sort",
            )
        ),
    ],
)
def buscar_tarjetas(
    conn: Db,
    id_cliente: Annotated[
        int | None, Query(alias="idCliente", gt=0, le=MAX_INT)
    ] = None,
    id_cuenta: Annotated[int | None, Query(alias="idCuenta", gt=0, le=MAX_INT)] = None,
    estado: EstadoTarjeta | None = None,
    es_extension: Annotated[bool | None, Query(alias="esExtension")] = None,
    page: Page = 1,
    page_size: PageSize = 20,
    sort: Sort = None,
) -> Any:
    """Busca tarjetas. Los filtros se pueden combinar. esExtension=false deja solo
    las principales (las que pueden ser titulares de una extensión).
    """
    return service.buscar_tarjetas(
        conn, id_cliente, id_cuenta, estado, page, page_size, sort, es_extension
    )


@router.get(
    "/por-renovar",
    operation_id="TARPorRenovar",
    response_model=PageTarjetaPorRenovar,
    dependencies=[
        Depends(require_roles(*POR_ID["tarjetas.consultar"].roles_iniciales)),
        Depends(solo_parametros("page", "pageSize")),
    ],
)
def por_renovar(
    conn: Db,
    agencia: Annotated[str, Depends(_agencia_operativa)],
    page: Page = 1,
    page_size: PageSize = 20,
) -> PageTarjetaPorRenovar:
    """Tarjetas de débito por vencer en la agencia operativa y sin reemisión vigente."""
    return service.listar_por_renovar(conn, agencia, page, page_size)


# TAR-03. Roles: ASESOR, SUPERVISOR, ADMIN
@router.get(
    "/{idTarjeta}",
    response_model=Tarjeta,
    dependencies=[
        Depends(require_roles(*POR_ID["tarjetas.consultar"].roles_iniciales))
    ],
)
def detalle_tarjeta(id_tarjeta: IdTarjetaPath, conn: Db) -> Any:
    """Detalle de una tarjeta."""
    tarjeta = service.obtener_tarjeta(conn, id_tarjeta)
    if tarjeta.estado_actual == "Solicitada":
        tarjeta.id_solicitud_aprobacion = aprobacion.id_solicitud(conn, id_tarjeta)
    return tarjeta


# TAR-04. Roles: ASESOR, SUPERVISOR, ADMIN
@router.post(
    "/{idTarjeta}/estado",
    response_model=Tarjeta,
    dependencies=[
        Depends(require_roles(*POR_ID["tarjetas.cambiarEstado"].roles_iniciales))
    ],
)
def cambiar_estado(
    id_tarjeta: IdTarjetaPath,
    payload: TarjetaEstadoUpdate,
    request: Request,
    operador: UsuarioActual,
    usuario: UsuarioAuditoria,
    conn: Db,
    conn_seguridad: Annotated[Connection, Depends(seguridad)],
) -> Any:
    """Cambia el estado de la tarjeta. Las solicitudes inscritas se resuelven en Aprobaciones."""
    return service.cambiar_estado(
        conn,
        conn_seguridad,
        id_tarjeta,
        payload,
        usuario,
        _ip(request),
        funciones=accesos.funciones_de_estado(operador.roles),
        tiene_solicitud=aprobacion.gestionada,
    )


@router.patch(
    "/{idTarjeta}/envio",
    operation_id="TAR08",
    response_model=EnvioTarjeta,
    dependencies=[
        Depends(require_roles(*POR_ID["tarjetas.cambiarEstado"].roles_iniciales)),
        Depends(solo_parametros()),
    ],
)
def actualizar_envio(
    id_tarjeta: IdTarjetaPath,
    payload: EnvioTarjetaUpdate,
    request: Request,
    operador: UsuarioActual,
    usuario: UsuarioAuditoria,
    conn: Db,
) -> EnvioTarjeta:
    """Registra el despacho de una tarjeta generada y su código de seguimiento."""
    return service.registrar_envio(
        conn,
        id_tarjeta,
        payload.codigo_seguimiento,
        operador.agencia(),
        usuario,
        _ip(request),
    )


# TAR-05. Roles: ASESOR, ADMIN
@router.post(
    "/{idTarjeta}/pin",
    status_code=204,
    dependencies=[
        Depends(require_roles(*POR_ID["tarjetas.asignarPin"].roles_iniciales)),
        Depends(_sin_body),
    ],
)
def regenerar_pin(
    id_tarjeta: IdTarjetaPath,
    request: Request,
    usuario: UsuarioAuditoria,
    conn: Db,
    conn_seguridad: Annotated[Connection, Depends(seguridad)],
) -> None:
    """Regenera el PIN (reposición o desbloqueo del PIN): el HSM genera uno nuevo y
    solo se guarda su IBM 3624 PIN Offset. No cambia el estado de la tarjeta.
    """
    service.regenerar_pin(conn, conn_seguridad, id_tarjeta, usuario, _ip(request))


# TAR-07. Roles: ASESOR, SUPERVISOR, ADMIN
@router.get(
    "/{idTarjeta}/sobre-pin",
    response_class=Response,
    responses=respuestas_pdf("Sobre de PIN (PDF). Se entrega una sola vez."),
    dependencies=[
        Depends(require_roles(*POR_ID["tarjetas.verSobrePin"].roles_iniciales)),
        Depends(solo_parametros()),
    ],
)
def sobre_pin(
    id_tarjeta: IdTarjetaPath,
    request: Request,
    usuario: UsuarioAuditoria,
    conn: Db,
) -> Response:
    """Descarga, una sola vez, el sobre de PIN de una tarjeta de débito: PDF con el PIN
    temporal para entregar al cliente con la tarjeta. Luego queda Entregado.
    """
    pdf = service.entregar_sobre_pin(conn, id_tarjeta, usuario, _ip(request))
    return respuesta_pdf(pdf, f"sobre-pin-{id_tarjeta}.pdf")


# TAR-06. Roles: SUPERVISOR, AUDITOR, ADMIN
@router.get(
    "/{idTarjeta}/historial",
    response_model=PageTarjetaHistorial,
    response_model_exclude_none=True,
    dependencies=[
        Depends(require_roles(*POR_ID["tarjetas.verHistorial"].roles_iniciales)),
        Depends(
            solo_parametros("fechaDesde", "fechaHasta", "page", "pageSize", "sort")
        ),
    ],
)
def historial_tarjeta(
    id_tarjeta: IdTarjetaPath,
    conn: Db,
    fecha_desde: Annotated[date | None, Query(alias="fechaDesde")] = None,
    fecha_hasta: Annotated[date | None, Query(alias="fechaHasta")] = None,
    page: Page = 1,
    page_size: PageSize = 20,
    sort: Sort = None,
) -> Any:
    """Eventos de la tarjeta, por defecto los más recientes primero.

    fechaDesde y fechaHasta incluyen ambos días.
    """
    return service.obtener_historial(
        conn, id_tarjeta, page, page_size, sort, fecha_desde, fecha_hasta
    )


def _solo_fuera_de_produccion() -> None:
    """El PIN pad simulado solo responde en development/test."""
    if get_settings().app_env not in ("development", "test"):
        raise problema(404, "NO_ENCONTRADO", "El recurso no existe.")


# PIN pad simulado (componente seguro de captura). Solo desarrollo y pruebas.
router_pruebas = APIRouter(
    prefix="/pruebas",
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    tags=["pruebas"],
    include_in_schema=False,
    dependencies=[
        Depends(_solo_fuera_de_produccion),
        Depends(require_auth),
        Depends(_sin_cache),
    ],
)


@router_pruebas.post(
    "/pin-block",
    response_model=PinBlockPrueba,
    dependencies=[Depends(require_roles("ADMIN"))],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": PinBlockPruebaEntrada.model_json_schema(by_alias=True)
                }
            },
        }
    },
)
def pin_block_prueba(
    entrada: Annotated[tuple[int, SecretStr], Depends(_leer_pin_prueba)],
    conn: Db,
    conn_seguridad: Annotated[Connection, Depends(seguridad)],
) -> Any:
    """Arma el PIN Block ISO-4 cifrado de una tarjeta, como lo haría el PIN pad, para
    usarlo en TAR-05 (o ATM-01). Solo en development/test.
    """
    id_tarjeta, pin = entrada
    return service.construir_pin_block_prueba(conn, conn_seguridad, id_tarjeta, pin)

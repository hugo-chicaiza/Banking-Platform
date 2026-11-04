import json
import re
from collections.abc import Callable, Iterator
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
from app.core.config.settings import get_settings
from app.core.database.db import cooperativa, get_engine
from app.core.security.auth import require_auth
from app.modules.tarjetas import service
from app.modules.tarjetas.schemas import (
    MAX_INT,
    MAX_PAGE_SIZE,
    MAX_PAGINA,
    EstadoTarjeta,
    PageTarjeta,
    PageTarjetaHistorial,
    PinAsignar,
    Tarjeta,
    TarjetaCreate,
    TarjetaEstadoUpdate,
)

# TODO(F-03): sacar el usuario del JWT. RealizadoPor y CreadoPor son NOT NULL, así que
# mientras tanto se guarda 0.
_USUARIO_SIN_IDENTIFICAR = 0
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
    """Conexión a SeguridadDB, donde está el hash del PIN."""
    with get_engine("seguridad").connect() as conn:
        yield conn


def autorizacion_disponible() -> None:
    """Sin F-03 cualquiera podría llamar estas rutas: solo responden en development."""
    if get_settings().app_env != "development":
        raise problema(
            503, "AUTORIZACION_NO_DISPONIBLE", "El servicio no está disponible."
        )


def _requiere_roles(*_roles: str) -> Callable[..., None]:
    """Roles permitidos en cada ruta.

    TODO(F-03): comparar _roles con los del JWT, responder 403 y registrar el intento.
    Por ahora solo aplica autorizacion_disponible.
    """

    def verificar(
        _disponible: Annotated[None, Depends(autorizacion_disponible)],
    ) -> None:
        return None

    return verificar


async def _leer_pin(request: Request) -> SecretStr:
    """Lee el body a mano: el error de Pydantic devuelve el valor recibido, aquí el PIN."""
    error = problema(400, "PIN_INVALIDO", "El PIN debe tener 4 dígitos.")
    contenido = bytearray()
    async for parte in request.stream():
        contenido += parte
        if len(contenido) > _MAX_BODY_PIN:
            raise error
    try:
        datos = json.loads(contenido)
    except ValueError:
        raise error from None
    if not isinstance(datos, dict) or set(datos) != {"pin"}:
        raise error
    pin = datos["pin"]
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{4}", pin):
        raise error
    return SecretStr(pin)


def _ip(request: Request) -> str | None:
    # X-Forwarded-For no se lee aquí porque el cliente puede falsificarlo. En Azure esta
    # será la IP del proxy hasta configurarlo.
    return request.client.host if request.client else None


# TAR-01. Roles: ASESOR, ADMIN
@router.post(
    "",
    response_model=Tarjeta,
    status_code=201,
    dependencies=[Depends(_requiere_roles("ASESOR", "ADMIN"))],
)
def emitir_tarjeta(payload: TarjetaCreate, request: Request, conn: Db) -> Any:
    """Emite una tarjeta en estado Generada y sin PIN para una cuenta Activa."""
    return service.crear_tarjeta(conn, payload, _USUARIO_SIN_IDENTIFICAR, _ip(request))


# TAR-02. Roles: ASESOR, SUPERVISOR, ADMIN
@router.get(
    "",
    response_model=PageTarjeta,
    dependencies=[
        Depends(_requiere_roles("ASESOR", "SUPERVISOR", "ADMIN")),
        Depends(
            solo_parametros(
                "idCliente", "idCuenta", "estado", "page", "pageSize", "sort"
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
    page: Page = 1,
    page_size: PageSize = 20,
    sort: Sort = None,
) -> Any:
    """Busca tarjetas. Los filtros se pueden combinar."""
    return service.buscar_tarjetas(
        conn, id_cliente, id_cuenta, estado, page, page_size, sort
    )


# TAR-03. Roles: ASESOR, SUPERVISOR, ADMIN
@router.get(
    "/{idTarjeta}",
    response_model=Tarjeta,
    dependencies=[Depends(_requiere_roles("ASESOR", "SUPERVISOR", "ADMIN"))],
)
def detalle_tarjeta(id_tarjeta: IdTarjetaPath, conn: Db) -> Any:
    """Detalle de una tarjeta."""
    return service.obtener_tarjeta(conn, id_tarjeta)


# TAR-04. Roles: ASESOR, SUPERVISOR, ADMIN
@router.post(
    "/{idTarjeta}/estado",
    response_model=Tarjeta,
    dependencies=[Depends(_requiere_roles("ASESOR", "SUPERVISOR", "ADMIN"))],
)
def cambiar_estado(
    id_tarjeta: IdTarjetaPath,
    payload: TarjetaEstadoUpdate,
    request: Request,
    conn: Db,
) -> Any:
    """Cambia el estado según Tarjeta.TransicionEstado. Para activar debe tener PIN."""
    return service.cambiar_estado(
        conn, id_tarjeta, payload, _USUARIO_SIN_IDENTIFICAR, _ip(request)
    )


# TAR-05. Roles: ASESOR, ADMIN
@router.post(
    "/{idTarjeta}/pin",
    status_code=204,
    dependencies=[Depends(_requiere_roles("ASESOR", "ADMIN"))],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": PinAsignar.model_json_schema(by_alias=True)
                }
            },
        }
    },
)
def asignar_pin(
    id_tarjeta: IdTarjetaPath,
    pin: Annotated[SecretStr, Depends(_leer_pin)],
    request: Request,
    conn: Db,
    conn_seguridad: Annotated[Connection, Depends(seguridad)],
) -> None:
    """Asigna el PIN inicial. Solo se puede hacer una vez."""
    service.asignar_pin(
        conn, conn_seguridad, id_tarjeta, pin, _USUARIO_SIN_IDENTIFICAR, _ip(request)
    )


# TAR-06. Roles: SUPERVISOR, AUDITOR, ADMIN
@router.get(
    "/{idTarjeta}/historial",
    response_model=PageTarjetaHistorial,
    response_model_exclude_none=True,
    dependencies=[
        Depends(_requiere_roles("SUPERVISOR", "AUDITOR", "ADMIN")),
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

"""Formato de errores de F-04 (RFC 7807) y traducción de los THROW de la BD.

Se activa router por router con route_class=ProblemDetailsRoute. Los módulos que no lo
usan siguen con su formato hasta que migren.
"""

import logging
import re
from collections.abc import Callable, Coroutine, Mapping
from http import HTTPStatus
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.api.middleware import obtener_trace_id

logger = logging.getLogger(__name__)

_MEDIA_TYPE = "application/problem+json"

# pyodbc cierra cada error con "(número nativo) (función ODBC)":
#   "... no permitido. (52005) (SQLExecDirectW)"
# Solo se lee ese número. El texto puede traer valores de la fila entre paréntesis
# ("The duplicate key value is (51234)") que no deben confundirse con un THROW.
_DB_NUMERO_RE = re.compile(r"\((\d+)\) \(SQL\w+\)")
# Violación de UNIQUE KEY (2627) y de índice único (2601) en SQL Server
_DB_DUPLICADO = frozenset({2627, 2601})
# Tabla de F-04. 52004 no aparece allí, pero lo necesita TAR-01
_DB_ERRORES: dict[int, tuple[int, str, str]] = {
    # Contabilidad responde lo mismo cuando lo detecta en Python (CON-02)
    51016: (
        500,
        "CALENDARIO_SIN_FECHA",
        "El calendario contable no tiene fechas cargadas para este período",
    ),
    52001: (409, "CLIENTE_NO_ACTIVO", "El cliente no está Activo."),
    52002: (409, "CUENTA_NO_ACTIVA", "La cuenta no está Activa."),
    52003: (422, "CUPO_EXCEDE_PRODUCTO", "El cupo excede el del producto."),
    52004: (422, "BIN_INVALIDO", "El BIN no corresponde al subproducto."),
    52005: (
        409,
        "TRANSICION_TARJETA_INVALIDA",
        "El cambio de estado de la tarjeta no está permitido.",
    ),
    52101: (409, "CLIENTE_NO_ACTIVO", "El cliente no está Activo."),
    52102: (409, "CLIENTE_NO_ACTIVO", "El cliente no está Activo."),
    52103: (422, "PRODUCTO_NO_ES_CUENTA", "El subproducto no es válido."),
    52104: (422, "PRODUCTO_NO_ES_CUENTA", "El subproducto no es de una cuenta."),
    52105: (
        422,
        "MONTO_APERTURA_INSUFICIENTE",
        "El monto inicial no cubre el mínimo de apertura.",
    ),
    57001: (409, "REGISTRO_INMUTABLE", "El registro histórico no se puede modificar."),
}

_ESQUEMA_PROBLEMA: dict[str, Any] = {
    "type": "object",
    "required": ["type", "title", "status", "code", "detail", "traceId"],
    "properties": {
        "type": {"type": "string"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "code": {"type": "string"},
        "detail": {"type": "string"},
        "traceId": {"type": "string"},
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        },
    },
}
# Para que /api/docs muestre el formato real de los errores
RESPUESTAS_ERROR: dict[int | str, dict[str, Any]] = {
    estado: {
        "description": HTTPStatus(estado).phrase,
        "content": {_MEDIA_TYPE: {"schema": _ESQUEMA_PROBLEMA}},
    }
    for estado in (400, 401, 403, 404, 409, 422, 429, 500)
}


def respuesta_problema(
    scope: Mapping[str, Any],
    status: int,
    code: str,
    detail: str,
    errors: list[dict[str, str]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    contenido: dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "code": code,
        "detail": detail,
        "traceId": obtener_trace_id(scope),
    }
    if errors:
        contenido["errors"] = errors
    return JSONResponse(
        contenido,
        status_code=status,
        media_type=_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            **(headers or {}),
        },
    )


def problema(status: int, code: str, message: str) -> HTTPException:
    """Error de negocio que ProblemDetailsRoute convierte en ProblemDetails.

    El mensaje lo ve el usuario: que sea fijo, sin ids ni datos de la petición.
    """
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def traducir_error_bd(
    exc: DBAPIError, *, operacion: str | None = None
) -> HTTPException:
    """Convierte un error de BD en HTTPException.

    Solo se lee exc.orig para sacar el número del THROW: str(exc) trae el SQL y sus
    parámetros, que pueden ser tokens o hashes.
    """
    numeros = [int(n) for n in _DB_NUMERO_RE.findall(str(exc.orig))]

    # CTA-08 publica otro nombre para el mismo THROW; los consumidores existentes
    # conservan CUPO_EXCEDE_PRODUCTO. Las traducciones siguen centralizadas aquí.
    if operacion == "CTA08" and 52003 in numeros:
        return problema(
            422,
            "CUPO_SUPERA_MAXIMO_PRODUCTO",
            "El cupo supera el máximo del subproducto en ese canal.",
        )

    duplicado = next((n for n in numeros if n in _DB_DUPLICADO), None)
    if duplicado is not None:
        # El mensaje de SQL Server trae el valor repetido (una cédula, por ejemplo):
        # solo se registra el número
        logger.warning("registro duplicado db_code=%s", duplicado)
        return problema(409, "REGISTRO_DUPLICADO", "El registro ya existe.")

    numero = next((n for n in numeros if 50000 <= n <= 59999), None)
    if numero is not None:
        status, code, mensaje = _DB_ERRORES.get(
            numero,
            (422, f"DB_{numero}", "La operación no cumple una regla de negocio."),
        )
        if status >= 500:
            logger.error("error de BD db_code=%s", numero)
        else:
            logger.warning("error de negocio en BD db_code=%s", numero)
        return problema(status, code, mensaje)
    logger.error("fallo de BD tipo=%s", type(exc.orig).__name__)
    return problema(500, "ERROR_INTERNO", "Error interno del servidor.")


def solo_parametros(*permitidos: str) -> Callable[[Request], None]:
    """Responde 400 si la consulta trae parámetros repetidos o que la ruta no conoce."""

    def verificar(request: Request) -> None:
        nombres = [nombre for nombre, _ in request.query_params.multi_items()]
        if len(nombres) != len(set(nombres)) or not set(nombres) <= set(permitidos):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "PARAMETRO_INVALIDO",
                    "message": "La consulta tiene parámetros repetidos o desconocidos.",
                },
            )

    return verificar


def _campos_invalidos(exc: RequestValidationError) -> list[dict[str, str]]:
    """Solo campo y motivo. Pydantic también trae el valor recibido en input."""
    campos = []
    for error in exc.errors():
        ubicacion = error.get("loc", ())
        if error.get("type") == "json_invalid":
            campos.append({"field": "body", "message": "JSON mal formado"})
            continue
        ruta = ubicacion[1:] or ubicacion
        campos.append(
            {
                "field": ".".join(str(parte) for parte in ruta),
                "message": str(error.get("msg", "Valor inválido")),
            }
        )
    return campos


def _respuesta_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detalle: Any = exc.detail
    if isinstance(detalle, dict):
        code = str(detalle.get("code", f"HTTP_{exc.status_code}"))
        mensaje = str(detalle.get("message", HTTPStatus(exc.status_code).phrase))
    else:
        code = f"HTTP_{exc.status_code}"
        mensaje = str(detalle)
    return respuesta_problema(
        request.scope, exc.status_code, code, mensaje, headers=exc.headers
    )


class ProblemDetailsRoute(APIRoute):
    """Devuelve ProblemDetails ante cualquier error en las rutas del router."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def manejar(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                return respuesta_problema(
                    request.scope,
                    400,
                    "DATOS_INVALIDOS",
                    "La solicitud tiene datos inválidos.",
                    errors=_campos_invalidos(exc),
                )
            except StarletteHTTPException as exc:
                # La línea de la petición no dice por qué se rechazó; esta sí, con el
                # mismo traceId
                detalle: Any = exc.detail
                if isinstance(detalle, dict):
                    logger.info(
                        "operacion rechazada status=%s code=%s",
                        exc.status_code,
                        detalle.get("code"),
                    )
                return _respuesta_http(request, exc)
            except DBAPIError as exc:
                return _respuesta_http(request, traducir_error_bd(exc))
            except SQLAlchemyError as exc:
                logger.error("fallo de BD tipo=%s", type(exc).__name__)
            except Exception as exc:  # noqa: BLE001 - lo que llegue aquí sale como 500 genérico
                logger.error(
                    "error inesperado tipo=%s trace_id=%s",
                    type(exc).__name__,
                    obtener_trace_id(request.scope),
                )
            return respuesta_problema(
                request.scope, 500, "ERROR_INTERNO", "Error interno del servidor."
            )

        return manejar

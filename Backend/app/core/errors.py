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

from app.core.middleware import obtener_trace_id

logger = logging.getLogger(__name__)

_MEDIA_TYPE = "application/problem+json"

# pyodbc deja el número entre paréntesis: "... no permitido. (52005) (SQLExecDirectW)"
_DB_CODIGO_RE = re.compile(r"\((5\d{4})\)")
# Tabla de F-04. 52004 no aparece allí, pero lo necesita TAR-01
_DB_ERRORES: dict[int, tuple[int, str, str]] = {
    52001: (409, "CLIENTE_NO_ACTIVO", "El cliente no está Activo."),
    52002: (409, "CUENTA_NO_ACTIVA", "La cuenta no está Activa."),
    52003: (422, "CUPO_EXCEDE_PRODUCTO", "El cupo excede el del producto."),
    52004: (422, "BIN_INVALIDO", "El BIN no corresponde al subproducto."),
    52005: (
        409,
        "TRANSICION_TARJETA_INVALIDA",
        "El cambio de estado de la tarjeta no está permitido.",
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
# Para que /docs muestre el formato real de los errores
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


def traducir_error_bd(exc: DBAPIError) -> HTTPException:
    """Convierte un error de BD en HTTPException.

    Solo se lee exc.orig para sacar el número del THROW: str(exc) trae el SQL y sus
    parámetros, que pueden ser tokens o hashes.
    """
    coincidencia = _DB_CODIGO_RE.search(str(exc.orig))
    if coincidencia:
        numero = int(coincidencia.group(1))
        status, code, mensaje = _DB_ERRORES.get(
            numero,
            (422, f"DB_{numero}", "La operación no cumple una regla de negocio."),
        )
        logger.warning("error de negocio en BD db_code=%s", numero)
        return HTTPException(
            status_code=status, detail={"code": code, "message": mensaje}
        )
    logger.error("fallo de BD tipo=%s", type(exc.orig).__name__)
    return HTTPException(
        status_code=500,
        detail={"code": "ERROR_INTERNO", "message": "Error interno del servidor."},
    )


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

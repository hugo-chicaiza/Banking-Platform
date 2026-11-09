"""ATM-01/09: autenticación y logout de sesiones ATM independientes de WorkOS."""

import asyncio
import json
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, problema
from app.core.database.db import get_engine
from app.modules.atm import saldo_service, service, session
from app.modules.atm.schemas import (
    ATMAuthRequest,
    ATMAuthResponse,
    AtmSaldoRequest,
    AtmSaldoResponse,
)
from app.modules.atm.terminal_auth import (
    TerminalAutenticado,
    require_terminal,
    revalidar_terminal,
)

_MAX_BODY_AUTH = 2048


class RutaATM(ProblemDetailsRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def manejar(request: Request):
            respuesta = await original(request)
            respuesta.headers["Cache-Control"] = "no-store"
            respuesta.headers["X-Content-Type-Options"] = "nosniff"
            return respuesta

        return manejar


router = APIRouter(
    prefix="/atm",
    tags=["ATM"],
    route_class=RutaATM,
    responses=RESPUESTAS_ERROR,
)


def _objeto_sin_duplicados(pares: list[tuple[str, Any]]) -> dict[str, Any]:
    datos: dict[str, Any] = {}
    for clave, valor in pares:
        if clave in datos:
            raise ValueError("JSON inválido")
        datos[clave] = valor
    return datos


async def leer_auth_atm(request: Request) -> ATMAuthRequest:
    """No expone valores sensibles de errores JSON o Pydantic ni registra el body."""
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != (
        "application/json"
    ):
        raise problema(415, "TIPO_CONTENIDO_INVALIDO", "Se requiere application/json.")
    if request.query_params:
        raise problema(400, "DATOS_INVALIDOS", "La solicitud tiene datos inválidos.")

    cuerpo = bytearray()
    async for fragmento in request.stream():
        if len(cuerpo) + len(fragmento) > _MAX_BODY_AUTH:
            raise problema(
                413, "SOLICITUD_DEMASIADO_GRANDE", "La solicitud es demasiado grande."
            )
        cuerpo.extend(fragmento)
    try:
        datos = json.loads(cuerpo, object_pairs_hook=_objeto_sin_duplicados)
        return ATMAuthRequest.model_validate(datos)
    except (ValueError, ValidationError):
        raise problema(
            400, "DATOS_INVALIDOS", "La solicitud tiene datos inválidos."
        ) from None


@dataclass(frozen=True)
class SolicitudAutenticada:
    terminal: TerminalAutenticado
    entrada: ATMAuthRequest


async def leer_solicitud_autenticada(
    request: Request,
    terminal: Annotated[TerminalAutenticado, Depends(require_terminal)],
) -> SolicitudAutenticada:
    # El cuerpo sensible solo se lee después de validar HTTPS y la credencial.
    entrada = await leer_auth_atm(request)
    if entrada.codigo_atm != terminal.codigo_atm:
        raise problema(
            401, "TERMINAL_NO_AUTORIZADO", "No se pudo autenticar el terminal."
        )
    return SolicitudAutenticada(terminal, entrada)


@router.post(
    "/auth",
    response_model=ATMAuthResponse,
    operation_id="ATM01",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": ATMAuthRequest.model_json_schema()}
            },
        }
    },
)
def autenticar_atm(
    request: Request,
    solicitud: Annotated[SolicitudAutenticada, Depends(leer_solicitud_autenticada)],
) -> ATMAuthResponse:
    # FastAPI ejecuta este handler síncrono en un worker. Cada conexión SQL se
    # crea y usa en ese mismo hilo; no se bloquea el bucle ASGI con SQL/HSM/RSA.
    emisor = session.preparar_emisor_atm()
    revalidar_terminal(solicitud.terminal)
    with get_engine("cooperativa").connect() as conn:
        acceso = asyncio.run(
            service.validar_acceso_atm(
                conn,
                solicitud.entrada,
                usuario_bloqueo=solicitud.terminal.audit_user_id,
                ip=request.client.host if request.client else None,
            )
        )
    revalidar_terminal(solicitud.terminal)
    return emisor.emitir(acceso)


async def leer_logout_atm(
    request: Request,
    sesion: Annotated[session.SesionATM, Depends(session.autenticar_sesion_atm)],
) -> session.SesionATM:
    if request.query_params:
        raise problema(
            400, "DATOS_INVALIDOS", "La solicitud no admite parámetros ni cuerpo."
        )
    async for fragmento in request.stream():
        if fragmento:
            raise problema(
                400, "DATOS_INVALIDOS", "La solicitud no admite parámetros ni cuerpo."
            )
    return sesion


@router.post(
    "/logout",
    status_code=204,
    response_class=Response,
    operation_id="ATM09",
    responses={
        503: {
            "description": "No se pudo comprobar o revocar la sesión ATM.",
            "content": RESPUESTAS_ERROR[500]["content"],
        }
    },
)
def cerrar_sesion_atm(
    sesion: Annotated[session.SesionATM, Depends(leer_logout_atm)],
) -> Response:
    # Un JWT ya revocado sigue siendo válido para repetir logout mientras no venza.
    session.revocar_sesion_atm(sesion)
    return Response(status_code=204)


@router.post(
    "/consulta-saldo",
    response_model=AtmSaldoResponse,
    operation_id="ATM02",
    # Tupla para reemplazar (no concatenar) las alternativas generadas por FastAPI.
    # Un único objeto expresa AND: sesión y credencial del terminal.
    openapi_extra={"security": ({"SesionATM": [], "APIKeyHeader": []},)},
    responses={
        503: {
            "description": "No se pudo confirmar la consulta de saldo.",
            "content": RESPUESTAS_ERROR[500]["content"],
        }
    },
)
def consultar_saldo_atm(
    request: Request,
    sesion: Annotated[session.SesionATM, Depends(session.require_sesion_operativa)],
    terminal: Annotated[TerminalAutenticado, Depends(require_terminal)],
    entrada: AtmSaldoRequest,
) -> AtmSaldoResponse:
    if request.query_params:
        raise problema(400, "DATOS_INVALIDOS", "La solicitud no admite parámetros.")
    try:
        with get_engine("cooperativa").connect() as conn:
            return saldo_service.consultar_saldo(
                conn,
                sesion,
                terminal,
                entrada,
                request.client.host if request.client else None,
            )
    except SQLAlchemyError:
        raise saldo_service._no_disponible() from None

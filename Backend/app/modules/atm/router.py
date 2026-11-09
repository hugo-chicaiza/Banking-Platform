"""ATM-01/09: autenticación y logout de sesiones ATM independientes de WorkOS."""

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, problema
from app.core.database.db import get_engine
from app.modules.atm import (
    cambio_pin_service,
    saldo_service,
    service,
    session,
    transferencias_service,
)
from app.modules.atm.schemas import (
    ATMAuthRequest,
    ATMAuthResponse,
    AtmCambioPinRequest,
    AtmSaldoRequest,
    AtmSaldoResponse,
    AtmTransferenciaRequest,
)
from app.modules.atm.terminal_auth import (
    TerminalAutenticado,
    require_terminal,
    revalidar_terminal,
)
from app.modules.transacciones.dependencias import (
    DependenciasOperacion,
    dependencias_operacion,
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


@dataclass(frozen=True, repr=False)
class CambioPinAutenticado:
    sesion: session.SesionATM
    terminal: TerminalAutenticado
    entrada: AtmCambioPinRequest


async def leer_cambio_pin_atm(
    request: Request,
    sesion: Annotated[session.SesionATM, Depends(session.require_sesion_atm)],
    terminal: Annotated[TerminalAutenticado, Depends(require_terminal)],
) -> CambioPinAutenticado:
    # Validar sesión y credencial antes de consumir el cuerpo sensible.
    if request.query_params:
        raise problema(400, "DATOS_INVALIDOS", "La solicitud no admite parámetros.")
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise problema(415, "TIPO_CONTENIDO_INVALIDO", "Se requiere application/json.")
    cuerpo = bytearray()
    async for fragmento in request.stream():
        if len(cuerpo) + len(fragmento) > _MAX_BODY_AUTH:
            raise problema(
                413, "SOLICITUD_DEMASIADO_GRANDE", "La solicitud es demasiado grande."
            )
        cuerpo.extend(fragmento)
    try:
        entrada = AtmCambioPinRequest.model_validate(
            json.loads(cuerpo, object_pairs_hook=_objeto_sin_duplicados)
        )
    except ValidationError as exc:
        bloque_invalido = any(
            error["type"] == "value_error"
            and error["loc"]
            in (("encryptedPinBlockActual",), ("encryptedPinBlockNuevo",))
            for error in exc.errors(
                include_input=False, include_context=False, include_url=False
            )
        )
        raise problema(
            422,
            "PIN_BLOCK_INVALIDO" if bloque_invalido else "DATOS_INVALIDOS",
            "El PIN Block no es válido."
            if bloque_invalido
            else "La solicitud tiene datos inválidos.",
        ) from None
    except ValueError:
        raise problema(
            422, "DATOS_INVALIDOS", "La solicitud tiene datos inválidos."
        ) from None
    return CambioPinAutenticado(sesion, terminal, entrada)


@router.post(
    "/cambio-pin",
    status_code=204,
    response_class=Response,
    operation_id="ATM06",
    openapi_extra={
        "security": ({"SesionATM": [], "APIKeyHeader": []},),
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": AtmCambioPinRequest.model_json_schema()}
            },
        },
    },
    responses={
        503: {
            "description": "Cambio no confirmado; requiere reconciliación.",
            "content": RESPUESTAS_ERROR[500]["content"],
        }
    },
)
def cambiar_pin_atm(
    request: Request,
    solicitud: Annotated[CambioPinAutenticado, Depends(leer_cambio_pin_atm)],
) -> Response:
    cambio_pin_service.cambiar_pin(
        solicitud.sesion,
        solicitud.terminal,
        solicitud.entrada,
        request.client.host if request.client else None,
    )
    return Response(status_code=204)


@dataclass(frozen=True, repr=False)
class TransferenciaAutenticada:
    sesion: session.SesionATM
    terminal: TerminalAutenticado
    entrada: AtmTransferenciaRequest


async def leer_transferencia_atm(
    request: Request,
    sesion: Annotated[session.SesionATM, Depends(session.require_sesion_operativa)],
    terminal: Annotated[TerminalAutenticado, Depends(require_terminal)],
) -> TransferenciaAutenticada:
    if request.query_params:
        raise problema(400, "DATOS_INVALIDOS", "La solicitud no admite parámetros.")
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise problema(415, "TIPO_CONTENIDO_INVALIDO", "Se requiere application/json.")
    cuerpo = bytearray()
    async for fragmento in request.stream():
        if len(cuerpo) + len(fragmento) > _MAX_BODY_AUTH:
            raise problema(
                413, "SOLICITUD_DEMASIADO_GRANDE", "La solicitud es demasiado grande."
            )
        cuerpo.extend(fragmento)
    try:
        # Evitar convertir primero a float y perder centavos en importes grandes.
        entrada = AtmTransferenciaRequest.model_validate(
            json.loads(
                cuerpo, parse_float=Decimal, object_pairs_hook=_objeto_sin_duplicados
            )
        )
    except (ValueError, ValidationError):
        raise problema(
            400, "DATOS_INVALIDOS", "La solicitud tiene datos inválidos."
        ) from None
    return TransferenciaAutenticada(sesion, terminal, entrada)


@router.post(
    "/transferencias",
    status_code=501,
    response_class=Response,
    operation_id="ATM05",
    description="Implementación parcial. Operación financiera deshabilitada hasta integrar G-06/AC-01 y resolver sus contratos pendientes.",
    openapi_extra={
        "security": ({"SesionATM": [], "APIKeyHeader": []},),
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": AtmTransferenciaRequest.model_json_schema()
                }
            },
        },
    },
    responses={
        501: {
            "description": "Operación financiera no habilitada.",
            "content": RESPUESTAS_ERROR[500]["content"],
        }
    },
)
def transferir_atm(
    solicitud: Annotated[TransferenciaAutenticada, Depends(leer_transferencia_atm)],
    dependencias: Annotated[DependenciasOperacion, Depends(dependencias_operacion)],
) -> Response:
    # No abrir CooperativaDB, numerar, calcular comisiones ni invocar escritores.
    transferencias_service.solicitar_transferencia(
        solicitud.sesion, solicitud.terminal, solicitud.entrada, dependencias
    )

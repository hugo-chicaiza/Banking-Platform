"""Emisión, validación y revocación de JWT ATM, independientes de WorkOS y HSM.

El llamador debe autenticar el terminal y validar tarjeta, PIN y cuentas antes de
entregar AccesoATMValidado. La clave de firma no se comparte con WorkOS ni el HSM.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import PyJWTError
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.core.security.pin_version import (
    PinVersionNoDisponible,
    validar_version,
    version_desde_fecha,
)
from app.modules.atm import repository
from app.modules.atm.schemas import ATMAuthResponse
from app.modules.atm.service import AccesoATMValidado

DURACION_SESION_ATM = 300
_bearer = HTTPBearer(auto_error=False, scheme_name="SesionATM", bearerFormat="JWT")


@dataclass(frozen=True, repr=False)
class SesionATM:
    jti: str
    fecha_expiracion: datetime
    id_atm: int
    id_tarjeta: int
    cuentas: tuple[int, ...]
    # Sesión restringida (PIN temporal): solo ATM-06 y ATM-09
    cambio_pin_requerido: bool = False
    pin_version: str | None = field(default=None, repr=False)


def _sesion_invalida() -> HTTPException:
    error = problema(401, "SESION_ATM_INVALIDA", "Se requiere una sesión ATM válida.")
    error.headers = {"WWW-Authenticate": "Bearer"}
    return error


def validar_jwt_atm(token: str) -> SesionATM:
    """Autenticidad y vigencia; no consulta revocaciones ni utiliza WorkOS/HSM."""
    emisor = preparar_emisor_atm()
    try:
        datos = jwt.decode(
            token,
            emisor.clave.public_key(),
            algorithms=["RS256"],
            issuer=emisor.issuer,
            audience=emisor.audience,
            options={
                "require": [
                    "iss",
                    "aud",
                    "iat",
                    "exp",
                    "jti",
                    "scope",
                    "idATM",
                    "idTarjeta",
                    "cuentas",
                    "cambioPinRequerido",
                ],
                "strict_aud": True,
            },
            leeway=0,
        )
        jti = datos["jti"]
        identificador = uuid.UUID(jti)
        cuentas = datos["cuentas"]
        restringida = datos["cambioPinRequerido"]
        # Los JWT previos sin versión solo pueden usarse para cerrar sesión.
        pin_version = (
            validar_version(datos["pinVersion"]) if "pinVersion" in datos else None
        )
        if (
            identificador.version != 4
            or str(identificador) != jti
            or datos["scope"] != "atm"
            or type(datos["iat"]) is not int
            or type(datos["exp"]) is not int
            or datos["exp"] - datos["iat"] != DURACION_SESION_ATM
            or not isinstance(cuentas, list)
            or type(restringida) is not bool
            # La sesión restringida no lleva cuentas; la normal, al menos una
            or bool(cuentas) == restringida
            or any(
                type(i) is not int or i <= 0
                for i in [datos["idATM"], datos["idTarjeta"], *cuentas]
            )
            or len(set(cuentas)) != len(cuentas)
        ):
            raise ValueError("Claims inválidos")
        return SesionATM(
            jti,
            datetime.fromtimestamp(datos["exp"], UTC),
            datos["idATM"],
            datos["idTarjeta"],
            tuple(cuentas),
            restringida,
            pin_version,
        )
    except (PyJWTError, ValueError, TypeError, AttributeError, OverflowError, OSError):
        raise _sesion_invalida() from None


def autenticar_sesion_atm(
    request: Request,
    _documentado: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> SesionATM:
    valores = [
        v for k, v in request.scope.get("headers", []) if k.lower() == b"authorization"
    ]
    if len(valores) != 1 or len(valores[0]) > 8192:
        raise _sesion_invalida()
    try:
        esquema, token = valores[0].decode("ascii").split(" ")
        if esquema.lower() != "bearer" or not token:
            raise ValueError("Cabecera inválida")
    except (ValueError, UnicodeError):
        raise _sesion_invalida() from None
    if request.scope.get("scheme") != "https":
        raise problema(400, "HTTPS_REQUERIDO", "Se requiere HTTPS.")
    return validar_jwt_atm(token)


def _revocaciones_no_disponibles() -> HTTPException:
    return problema(
        503, "SESION_ATM_NO_DISPONIBLE", "No se pudo comprobar la sesión ATM."
    )


def require_sesion_atm(
    sesion: Annotated[SesionATM, Depends(autenticar_sesion_atm)],
) -> SesionATM:
    """Dependencia obligatoria de operaciones ATM con sesión; no usar en logout."""
    try:
        with get_engine("seguridad").connect() as conn:
            revocada = repository.sesion_atm_revocada(conn, sesion.jti)
    except SQLAlchemyError:
        raise _revocaciones_no_disponibles() from None
    if revocada:
        raise _sesion_invalida()
    return sesion


def require_sesion_pin_actual(
    sesion: Annotated[SesionATM, Depends(require_sesion_atm)],
) -> SesionATM:
    """Compartida por operaciones y futuro ATM-06; nunca aplicar a logout."""
    if sesion.pin_version is None:
        raise _sesion_invalida()
    try:
        validar_version(sesion.pin_version)
        with get_engine("seguridad").connect() as conn:
            actual = repository.obtener_asignacion_pin_actual(conn, sesion.id_tarjeta)
        if actual is None:
            raise _sesion_invalida()
        version = version_desde_fecha(actual.get("fecha_asignacion"))
    except (SQLAlchemyError, PinVersionNoDisponible):
        raise _revocaciones_no_disponibles() from None
    if version != sesion.pin_version:
        raise _sesion_invalida()
    intentos = actual.get("intentos_fallidos")
    pendiente = actual.get("requiere_cambio")
    if (
        actual.get("tiene_pin_asignado") is not True
        or actual.get("estado_pin") != "Activo"
        or type(intentos) is not int
        or intentos < 0
        or intentos >= 3
        or type(pendiente) is not bool
    ):
        raise problema(403, "OPERACION_NO_PERMITIDA", "El PIN no permite operar.")
    if (
        pendiente or actual.get("coordinacion_pendiente", False)
    ) and not sesion.cambio_pin_requerido:
        raise problema(
            403, "PIN_CAMBIO_REQUERIDO", "Debe cambiar el PIN antes de operar."
        )
    return sesion


def require_sesion_operativa(
    sesion: Annotated[SesionATM, Depends(require_sesion_pin_actual)],
) -> SesionATM:
    """Para operaciones con cuentas (ATM-02 a ATM-08, salvo ATM-06): rechaza la sesión
    restringida de un PIN temporal, que solo sirve para cambiar el PIN o cerrar sesión.
    """
    if sesion.cambio_pin_requerido:
        raise problema(
            403,
            "PIN_CAMBIO_REQUERIDO",
            "Debe cambiar el PIN antes de operar.",
        )
    return sesion


def revocar_sesion_atm(sesion: SesionATM) -> None:
    try:
        with get_engine("seguridad").begin() as conn:
            repository.revocar_sesion_atm(conn, sesion.jti, sesion.fecha_expiracion)
    except SQLAlchemyError:
        # También captura fallos de commit: nunca responder 204 antes de confirmar.
        raise _revocaciones_no_disponibles() from None


def preparar_emisor_atm() -> "EmisorSesionATM":
    """Comprueba la configuración de firma antes de procesar tarjeta o PIN."""
    settings = get_settings()
    pem = settings.atm_jwt_private_key_pem.get_secret_value()
    if (
        not pem
        or not settings.atm_jwt_issuer.strip()
        or not settings.atm_jwt_audience.strip()
    ):
        raise _sesion_no_disponible()

    try:
        clave = load_pem_private_key(pem.encode(), password=None)
        if not isinstance(clave, RSAPrivateKey) or clave.key_size < 2048:
            raise _sesion_no_disponible()
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise _sesion_no_disponible() from None
    return EmisorSesionATM(clave, settings.atm_jwt_issuer, settings.atm_jwt_audience)


@dataclass(frozen=True)
class EmisorSesionATM:
    clave: RSAPrivateKey = field(repr=False)
    issuer: str
    audience: str

    def emitir(self, acceso: AccesoATMValidado) -> ATMAuthResponse:
        ids_cuentas = [cuenta.id_cuenta for cuenta in acceso.cuentas]
        ids = [acceso.id_atm, acceso.id_tarjeta, *ids_cuentas]
        restringida = acceso.cambio_pin_requerido
        try:
            pin_version = validar_version(acceso.pin_version)
        except PinVersionNoDisponible:
            raise _sesion_no_disponible() from None
        if (
            type(restringida) is not bool
            # La sesión restringida no lleva cuentas; la normal, al menos una
            or bool(ids_cuentas) == restringida
            or any(
                type(identificador) is not int or identificador <= 0
                for identificador in ids
            )
            or len(set(ids_cuentas)) != len(ids_cuentas)
        ):
            raise _sesion_no_disponible()
        ahora = int(datetime.now(UTC).timestamp())
        # Lista explícita: jamás serializar el contexto, el request ni las cuentas
        # completas, que podrían incorporar datos sensibles en el futuro.
        claims = {
            "iss": self.issuer,
            "aud": self.audience,
            "iat": ahora,
            "exp": ahora + DURACION_SESION_ATM,
            "jti": str(uuid.uuid4()),
            "scope": "atm",
            "idATM": acceso.id_atm,
            "idTarjeta": acceso.id_tarjeta,
            "cuentas": ids_cuentas,
            "cambioPinRequerido": restringida,
            "pinVersion": pin_version,
        }
        try:
            token = jwt.encode(
                claims, self.clave, algorithm="RS256", headers={"typ": "JWT"}
            )
        except (ValueError, TypeError, UnsupportedAlgorithm, PyJWTError):
            raise _sesion_no_disponible() from None

        return ATMAuthResponse(
            session_token=token,
            titular=acceso.titular,
            cambio_pin_requerido=restringida,
            cuentas=acceso.cuentas,
        )


def emitir_sesion_atm(acceso: AccesoATMValidado) -> ATMAuthResponse:
    return preparar_emisor_atm().emitir(acceso)


def _sesion_no_disponible():
    return problema(503, "SESION_ATM_NO_DISPONIBLE", "No se pudo emitir la sesión ATM.")

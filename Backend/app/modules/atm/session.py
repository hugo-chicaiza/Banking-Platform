"""Emisión local de JWT ATM. No autentica terminales ni registra endpoints.

El llamador debe autenticar el terminal y validar tarjeta, PIN y cuentas antes de
entregar AccesoATMValidado. La clave de firma no se comparte con WorkOS ni el HSM.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from jwt.exceptions import PyJWTError

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.modules.atm.schemas import ATMAuthResponse
from app.modules.atm.service import AccesoATMValidado

DURACION_SESION_ATM = 300


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
        if (
            not ids_cuentas
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
            cuentas=acceso.cuentas,
        )


def emitir_sesion_atm(acceso: AccesoATMValidado) -> ATMAuthResponse:
    return preparar_emisor_atm().emitir(acceso)


def _sesion_no_disponible():
    return problema(503, "SESION_ATM_NO_DISPONIBLE", "No se pudo emitir la sesión ATM.")

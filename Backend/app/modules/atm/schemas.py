from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.core.api.schemas import CamelModel

CodigoATM = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=8,
        max_length=8,
    ),
]

TipoCuentaATM = Literal["Ahorro", "Corriente"]


class CuentaATM(CamelModel):
    """Cuenta autorizada para operar desde el ATM."""

    id_cuenta: int = Field(gt=0)
    numero_cuenta_enmascarado: str
    tipo_cuenta: TipoCuentaATM


class ATMAuthResponse(CamelModel):
    """Respuesta de autenticación ATM-01."""

    session_token: str
    expires_in: Literal[300] = 300
    titular: str
    cuentas: list[CuentaATM]


class ATMAuthRequest(CamelModel):
    """Solicitud de autenticación ATM-01."""

    codigo_atm: CodigoATM
    id_tarjeta: int = Field(gt=0)
    encrypted_pin_block: str = Field(
        min_length=32,
        max_length=32,
        pattern=r"^[0-9a-fA-F]{32}$",
    )
    key_reference: str = Field(min_length=1, max_length=100)

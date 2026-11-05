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

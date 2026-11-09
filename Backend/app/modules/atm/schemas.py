import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

from app.core.api.schemas import CamelModel, Money

CodigoATM = Annotated[
    str,
    StringConstraints(
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
    # PIN temporal (A-05): la sesión solo sirve para cambiar el PIN (ATM-06)
    cambio_pin_requerido: bool = False
    cuentas: list[CuentaATM]


class ATMAuthRequest(CamelModel):
    """Contrato ATM-01. El router lee el body sin devolver errores con su contenido."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_by_name=False)

    codigo_atm: CodigoATM = Field(alias="codigoATM")
    numero_tarjeta: SecretStr = Field(
        repr=False, json_schema_extra={"pattern": r"^[0-9]{12,19}$"}
    )
    encrypted_pin_block: SecretStr = Field(
        repr=False, json_schema_extra={"pattern": r"^[0-9a-fA-F]{32}$"}
    )
    key_reference: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")

    @field_validator("numero_tarjeta", "encrypted_pin_block", mode="before")
    @classmethod
    def _validar_secreto(cls, valor: object, info: ValidationInfo) -> str:
        patron = (
            r"[0-9]{12,19}"
            if info.field_name == "numero_tarjeta"
            else r"[0-9a-fA-F]{32}"
        )
        if not isinstance(valor, str) or re.fullmatch(patron, valor) is None:
            raise ValueError("Campo sensible inválido")
        return valor


class AtmSaldoRequest(CamelModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_by_name=False)

    id_cuenta: int = Field(gt=0, le=2147483647)
    registro_unico: str = Field(pattern=r"^[A-Za-z0-9]{12}$")


class AtmCambioPinRequest(CamelModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_by_name=False)

    encrypted_pin_block_actual: SecretStr = Field(
        repr=False, json_schema_extra={"pattern": r"^[0-9a-fA-F]{32}$"}
    )
    encrypted_pin_block_nuevo: SecretStr = Field(
        repr=False, json_schema_extra={"pattern": r"^[0-9a-fA-F]{32}$"}
    )
    key_reference: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")

    @field_validator(
        "encrypted_pin_block_actual", "encrypted_pin_block_nuevo", mode="before"
    )
    @classmethod
    def _bloque(cls, valor: object) -> str:
        if (
            not isinstance(valor, str)
            or re.fullmatch(r"[0-9a-fA-F]{32}", valor) is None
        ):
            raise ValueError("Bloque inválido")
        return valor


class AtmSaldoResponse(CamelModel):
    id_transaccion: int
    numero_comprobante: str
    tipo_transaccion: Literal["Consulta"] = "Consulta"
    estado: Literal["Completada"] = "Completada"
    codigo_respuesta: Literal["00"] = "00"
    comision: Money
    saldo_contable: Money
    saldo_retenido: Money
    saldo_disponible: Money
    fecha_hora_sistema: datetime
    fecha_consulta_saldo: datetime
    es_reintento: bool

"""Credenciales temporales de terminal. Independiente del PIN, HSM y JWT."""

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from app.core.api.errors import problema
from app.core.config.settings import get_settings

MAX_REGISTRY_BYTES = 262144
MAX_SOLAPE = timedelta(minutes=15)
ID_CREDENCIAL = r"[A-Za-z0-9_-]{16,64}"
_HEADER = re.compile(rb"([A-Za-z0-9_-]{16,64})\.([A-Za-z0-9_-]{43})")
_api_key = APIKeyHeader(
    name="X-ATM-Credential",
    auto_error=False,
    description="Credencial individual del agente ATM; nunca del frontend.",
)


class RegistroCredencial(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    codigo_atm: str = Field(alias="codigoATM", pattern=r"^[A-Za-z0-9_-]{8}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    enabled: StrictBool
    not_before: AwareDatetime = Field(alias="notBefore")
    expires_at: AwareDatetime = Field(alias="expiresAt")
    audit_user_id: int = Field(alias="auditUserId", strict=True, gt=0, le=2147483647)

    @model_validator(mode="after")
    def _intervalo(self):
        if self.expires_at <= self.not_before:
            raise ValueError("Intervalo inválido")
        return self


@dataclass(frozen=True)
class TerminalAutenticado:
    credential_id: str
    codigo_atm: str
    audit_user_id: int
    digest: bytes = field(repr=False)


def _pares_unicos(pares):
    datos = {}
    for clave, valor in pares:
        if clave in datos:
            raise ValueError("Registro inválido")
        datos[clave] = valor
    return datos


def validar_registro(contenido: bytes) -> dict[str, RegistroCredencial]:
    if len(contenido) > MAX_REGISTRY_BYTES:
        raise ValueError("Registro inválido")
    json.loads(contenido, object_pairs_hook=_pares_unicos)
    registros = TypeAdapter(dict[str, RegistroCredencial]).validate_json(
        contenido, strict=True
    )
    ahora = datetime.now(UTC)
    por_terminal: dict[str, list[RegistroCredencial]] = {}
    for identificador, registro in registros.items():
        if re.fullmatch(ID_CREDENCIAL, identificador) is None:
            raise ValueError("Registro inválido")
        if registro.enabled and registro.expires_at > ahora:
            por_terminal.setdefault(registro.codigo_atm, []).append(registro)
    for grupo in por_terminal.values():
        if len(grupo) > 2:
            raise ValueError("Demasiadas credenciales activas")
        if len(grupo) == 2:
            a, b = grupo
            if (
                min(a.expires_at, b.expires_at) - max(a.not_before, b.not_before)
                > MAX_SOLAPE
            ):
                raise ValueError("Solape excesivo")
    return registros


def leer_registro() -> dict[str, RegistroCredencial]:
    ruta = get_settings().atm_terminal_credentials_file
    try:
        path = Path(ruta)
        if not ruta or not path.is_absolute():
            raise ValueError("Falta configuración")
        with path.open("rb") as archivo:
            contenido = archivo.read(MAX_REGISTRY_BYTES + 1)
        return validar_registro(contenido)
    except (OSError, ValueError, ValidationError):
        raise problema(
            503, "ATM_AUTH_NO_DISPONIBLE", "No se pudo autenticar el terminal."
        ) from None


def _vigente(registro: RegistroCredencial) -> bool:
    ahora = datetime.now(UTC)
    return registro.enabled and registro.not_before <= ahora < registro.expires_at


def _denegado() -> HTTPException:
    return problema(401, "TERMINAL_NO_AUTORIZADO", "No se pudo autenticar el terminal.")


def autenticar_credencial(valor: bytes) -> TerminalAutenticado:
    coincidencia = _HEADER.fullmatch(valor)
    if coincidencia is None:
        raise _denegado()
    identificador, secreto = coincidencia.groups()
    # Exige la representación canónica de 32 bytes, sin variantes del último sexteto.
    binario = base64.b64decode(secreto + b"=", altchars=b"-_", validate=True)
    if len(binario) != 32 or base64.urlsafe_b64encode(binario).rstrip(b"=") != secreto:
        raise _denegado()
    registros = leer_registro()
    registro = registros.get(identificador.decode("ascii"))
    digest = hashlib.sha256(secreto).digest()
    esperado = bytes.fromhex(registro.sha256) if registro is not None else bytes(32)
    coincide = hmac.compare_digest(digest, esperado)
    if registro is None or not coincide or not _vigente(registro):
        raise _denegado()
    return TerminalAutenticado(
        identificador.decode(), registro.codigo_atm, registro.audit_user_id, digest
    )


def revalidar_terminal(terminal: TerminalAutenticado) -> None:
    """Relee la fuente autoritativa: nunca cachea revocaciones entre peticiones."""
    registro = leer_registro().get(terminal.credential_id)
    if (
        registro is None
        or not _vigente(registro)
        or registro.codigo_atm != terminal.codigo_atm
        or registro.audit_user_id != terminal.audit_user_id
        or not hmac.compare_digest(bytes.fromhex(registro.sha256), terminal.digest)
    ):
        raise _denegado()


def require_terminal(
    request: Request,
    _valor_documentado: Annotated[str | None, Security(_api_key)],
) -> TerminalAutenticado:
    # El esquema solo puede elevarlo un proxy configurado como confiable en el
    # servidor ASGI. Nunca interpretar X-Forwarded-Proto directamente aquí.
    if request.scope.get("scheme") != "https":
        raise problema(403, "HTTPS_REQUERIDO", "Se requiere HTTPS.")
    valores = [
        v
        for k, v in request.scope.get("headers", [])
        if k.lower() == b"x-atm-credential"
    ]
    if len(valores) != 1 or len(valores[0]) > 108:
        raise _denegado()
    return autenticar_credencial(valores[0])

"""Contrato de funciones independiente del editor anterior de pestañas."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictBool, StringConstraints

from app.core.api.schemas import CamelModel
from app.core.security.auth import Rol

IdFuncion = Annotated[str, StringConstraints(pattern=r"^[a-z][a-zA-Z0-9.]{0,79}$")]
Version = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Motivo = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=10,
        max_length=160,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]


class AjusteFuncion(CamelModel):
    model_config = ConfigDict(extra="forbid")
    funcion: IdFuncion
    rol: str
    permitido: StrictBool


class CambioFuncion(CamelModel):
    model_config = ConfigDict(extra="forbid")
    funcion: IdFuncion
    rol: Rol
    permitido: StrictBool | None


class CambiosFunciones(CamelModel):
    model_config = ConfigDict(extra="forbid")
    version: Version
    motivo: Motivo
    cambios: Annotated[list[CambioFuncion], Field(min_length=1, max_length=400)]


class FuncionVista(CamelModel):
    id: str
    nombre: str
    modulo: str
    rutas: list[str]
    roles_iniciales: list[str]
    delegable: bool
    motivo_proteccion: str | None
    dependencias: list[str]


class ConfiguracionFunciones(CamelModel):
    version: Version
    activa: bool
    modelo: Literal["FUNCIONES_POR_ROL"] = "FUNCIONES_POR_ROL"
    roles: list[str]
    funciones: list[FuncionVista]
    ajustes: list[AjusteFuncion]


class FuncionesGuardadas(ConfiguracionFunciones):
    estado: Literal["GUARDADO"] = "GUARDADO"
    cambios_aplicados: int


class AutorizacionFunciones(CamelModel):
    version: Version
    activa: Literal[True] = True
    funciones: list[str]
    rutas: list[str]

"""Contratos aditivos de usuarios multiagencia (#450)."""

from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints

from app.core.api.schemas import CamelModel

AgenciaId = Annotated[str, StringConstraints(pattern=r"^[0-9]{3}$")]


class AgenciaAsignada(CamelModel):
    id_agencia: str
    codigo: str
    estado: str
    principal: bool = False


class AsignacionesUsuario(CamelModel):
    id_usuario: int
    id_agencia_principal: str | None
    agencias: list[AgenciaAsignada]
    version: int


class AsignacionesEntrada(CamelModel):
    model_config = ConfigDict(extra="forbid")
    id_agencias: list[AgenciaId] = Field(max_length=100)
    id_agencia_principal: AgenciaId | None
    version: int = Field(ge=0)


class SeleccionAgencia(CamelModel):
    model_config = ConfigDict(extra="forbid")
    id_agencia: AgenciaId | None


class TrasladoUsuario(CamelModel):
    model_config = ConfigDict(extra="forbid")
    id_agencia: AgenciaId


class ContextoAgencias(CamelModel):
    id_agencia: str | None
    agencia_es_matriz: bool = False
    id_agencia_principal: str | None
    agencias_asignadas: list[AgenciaAsignada]
    agencias_permitidas: list[AgenciaAsignada]
    requiere_seleccion_agencia: bool
    alcance_global: bool = False
    acceso_todas_agencias: bool = False


class CambioAgencia(CamelModel):
    id_historial: int
    id_agencia: str | None
    accion: str
    principal_anterior: str | None
    principal_nueva: str | None
    realizado_por: int | None
    nombre_actor: str | None = None
    agencia_actor: str | None
    fecha_utc: datetime


class HistorialAgencias(CamelModel):
    items: list[CambioAgencia]
    page: int
    page_size: int
    total: int

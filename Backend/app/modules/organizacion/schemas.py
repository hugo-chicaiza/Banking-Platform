from typing import Literal

from pydantic import ConfigDict

from app.core.api.schemas import CamelModel

EstadoAgencia = Literal["A", "I", "C"]


class AgenciaEstadoUpdate(CamelModel):
    model_config = ConfigDict(extra="forbid")
    estado: EstadoAgencia


class AgenciaEstado(CamelModel):
    id_agencia: str
    estado: EstadoAgencia

"""Manejadores explicitos por operacion; el cliente no puede seleccionar codigo ejecutable."""

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from sqlalchemy import Connection

from app.core.api.errors import problema


@dataclass(frozen=True)
class Objetivo:
    tipo: str
    id: str
    agencia: str | None


@dataclass(frozen=True)
class Plan:
    contenido: dict[str, Any]
    antes: dict[str, Any]
    despues: dict[str, Any]
    version: str


class Manejador(Protocol):
    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan: ...

    def version(self, conn: Connection, objetivo: Objetivo) -> str: ...

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict[str, Any],
        solicitante: str,
        id_solicitud: int,
    ) -> None: ...


@dataclass(frozen=True)
class Operacion:
    codigo: str
    tipo_objetivo: str
    base: Literal["cooperativa", "seguridad"]
    roles_ejecucion: frozenset[str]
    permiso_aprobacion: str
    manejador: Manejador


class Registro:
    def __init__(self) -> None:
        self._operaciones: dict[tuple[str, str], Operacion] = {}

    def agregar(self, operacion: Operacion) -> None:
        llave = (operacion.codigo, operacion.tipo_objetivo)
        if llave in self._operaciones:
            raise ValueError("La operacion ya tiene un manejador registrado.")
        self._operaciones[llave] = operacion

    def obtener(self, codigo: str, tipo: str) -> Operacion:
        operacion = self._operaciones.get((codigo, tipo))
        if operacion is None:
            raise problema(
                404, "OPERACION_NO_DISPONIBLE", "La operacion no esta disponible."
            )
        return operacion

    def operaciones(self) -> tuple[Operacion, ...]:
        return tuple(self._operaciones.values())

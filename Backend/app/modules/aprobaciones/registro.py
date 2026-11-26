"""Manejadores explicitos por operacion; el cliente no puede seleccionar codigo ejecutable."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.modules.aprobaciones.identidad import Actor


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
    tabla_auditada: str | None = None
    evento_ejecucion: str | Callable[[dict[str, Any]], str] = "APR_OPERACION_EJECUTADA"
    solicitud_directa: bool = True
    permiso_ejecucion: str | None = None
    aplicar_con_aprobador: Callable[[Connection, Objetivo, int], None] | None = None
    solicitud_unica: bool = False
    aplicar_diferido: bool = False
    validar_aprobador: Callable[[Objetivo, int], None] | None = None
    contexto_aplicacion: Callable[[], AbstractContextManager[None]] | None = None
    cancelable_por_solicitante: bool = True
    cancelar_por_revocacion: bool = True
    aplicar_descarte: Callable[[Connection, dict[str, Any]], None] | None = None
    roles_aprobacion: frozenset[str] | None = None

    def permite_aprobar(self, actor: Actor) -> bool:
        if self.roles_aprobacion is not None:
            return not self.roles_aprobacion.isdisjoint(actor.roles)
        return self.permiso_aprobacion in actor.permisos


class Registro:
    def __init__(self) -> None:
        self._operaciones: dict[tuple[str, str], Operacion] = {}

    def agregar(self, operacion: Operacion) -> None:
        llave = (operacion.codigo, operacion.tipo_objetivo)
        if llave in self._operaciones:
            raise ValueError("La operacion ya tiene un manejador registrado.")
        self._operaciones[llave] = operacion

    def buscar(self, codigo: str, tipo: str) -> Operacion | None:
        return self._operaciones.get((codigo, tipo))

    def obtener(self, codigo: str, tipo: str) -> Operacion:
        operacion = self.buscar(codigo, tipo)
        if operacion is None:
            raise problema(
                404, "OPERACION_NO_DISPONIBLE", "La operacion no esta disponible."
            )
        return operacion

    def operaciones(self) -> tuple[Operacion, ...]:
        return tuple(self._operaciones.values())

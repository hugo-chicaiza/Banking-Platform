"""Baja de agencias con el registro de operaciones de E0-08."""

import re
from datetime import date
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection

from app.core.api.errors import problema
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.organizacion import repository, service
from app.modules.organizacion.schemas import PropuestaBajaAgencia

CODIGO_BAJA = "ORG-AGENCIA-EDITAR"
TIPO_OBJETIVO = "Agencia"


class BajaAgencia:
    def _leer(self, conn: Connection, objetivo: Objetivo) -> dict[str, Any]:
        if (
            objetivo.agencia != objetivo.id
            or not re.fullmatch(r"[0-9A-Z]{3}", objetivo.id)
            or objetivo.id == "000"
        ):
            raise problema(422, "OBJETIVO_INVALIDO", "Seleccione la agencia objetivo.")
        fila = repository.obtener_agencia(conn, objetivo.id, bloquear=True)
        if fila is None:
            raise problema(404, "AGENCIA_NO_ENCONTRADA", "La agencia no existe.")
        return fila

    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan:
        try:
            datos = PropuestaBajaAgencia.model_validate(contenido)
        except ValidationError:
            raise problema(
                422, "CONTENIDO_INVALIDO", "La baja solo admite el motivo."
            ) from None
        fila = self._leer(conn, objetivo)
        service.validar_desactivacion(conn, objetivo.id, fila)
        antes = service.a_respuesta(fila).model_dump(mode="json", by_alias=True)
        return Plan(
            datos.model_dump(mode="json", by_alias=True),
            antes,
            {**antes, "estado": "I"},
            self.version(conn, objetivo),
        )

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        version = repository.version_agencia(conn, objetivo.id)
        if version is None:
            raise problema(409, "SOLICITUD_DESACTUALIZADA", "La agencia ya no existe.")
        return version

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict[str, Any],
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        fila = self._leer(conn, objetivo)
        service.validar_desactivacion(conn, objetivo.id, fila)
        if not repository.actualizar_estado(conn, objetivo.id, "A", "I"):
            raise problema(
                409, "SOLICITUD_DESACTUALIZADA", "La agencia cambio de estado."
            )


OPERACION_BAJA = Operacion(
    CODIGO_BAJA,
    TIPO_OBJETIVO,
    "cooperativa",
    frozenset({"ADMIN"}),
    "agencias:aprobar",
    BajaAgencia(),
    tabla_auditada=service.TABLA,
    evento_ejecucion="ORG_AGENCIA_ESTADO",
    solicitud_directa=False,
)

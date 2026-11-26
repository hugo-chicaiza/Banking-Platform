"""E5-07: cambios de estado del cliente con aprobación (cola E0-08)."""

import hashlib
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.core.api.schemas import CamelModel
from app.core.database.db import get_engine
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.clientes import repository, service

CODIGO_ESTADO = "CLI-ESTADO"
TIPO_OBJETIVO = "ClienteEstado"


def objetivo(id_cliente: int) -> Objetivo:
    return Objetivo(TIPO_OBJETIVO, str(id_cliente), None)


class ContenidoEstado(CamelModel):
    model_config = ConfigDict(extra="forbid")

    estado: Literal["Bloqueado", "Activo", "Eliminado"]
    motivo: str = Field(min_length=1, max_length=300)
    modificado_por: Annotated[int, Field(gt=0)]
    direccion_ip: str = Field(min_length=1, max_length=45)

    @field_validator("motivo")
    @classmethod
    def motivo_no_vacio(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("El motivo no puede contener solo espacios.")
        return valor


def _contenido(contenido: dict[str, Any]) -> ContenidoEstado:
    try:
        return ContenidoEstado.model_validate(contenido)
    except ValidationError:
        raise problema(
            422,
            "CONTENIDO_INVALIDO",
            "El cambio de estado propuesto no cumple el contrato.",
        ) from None


def _leer(conn: Connection, objetivo: Objetivo) -> dict[str, Any]:
    if not objetivo.id.isdigit() or objetivo.agencia is not None:
        raise problema(422, "OBJETIVO_INVALIDO", "Seleccione el cliente objetivo.")
    fila = repository.bloquear_cliente(conn, int(objetivo.id))
    if fila is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "No se encontró el cliente.")
    return fila


def validar_aprobador_estado(objetivo: Objetivo, id_interno: int) -> None:
    if not objetivo.id.isdigit():
        raise problema(422, "OBJETIVO_INVALIDO", "Seleccione el cliente objetivo.")
    engine = get_engine("cooperativa")
    with engine.connect() as conn:
        fila = (
            conn.execute(
                text("SELECT CreadoPor FROM Clientes.Cliente WHERE IdCliente = :id"),
                {"id": int(objetivo.id)},
            )
            .mappings()
            .first()
        )
        if fila is not None and fila["CreadoPor"] == id_interno:
            raise problema(
                403,
                "APROBADOR_INCOMPATIBLE",
                "Quien registró al cliente no puede aprobar su cambio de estado.",
            )


class ManejadorEstado:
    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan:
        datos = _contenido(contenido)
        fila = _leer(conn, objetivo)
        id_cliente = fila["id_cliente"]
        actual = fila["estado"]
        if datos.estado not in service._TRANSICIONES_CLIENTE.get(actual, set()):
            raise problema(
                409,
                "TRANSICION_INVALIDA",
                "El cambio de estado no está permitido.",
            )
        if datos.estado == "Eliminado":
            service._validar_productos_cliente(conn, id_cliente)
        return Plan(
            datos.model_dump(mode="json", by_alias=True),
            {"estado": actual},
            {"estado": datos.estado},
            self.version(conn, objetivo),
        )

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        fila = _leer(conn, objetivo)
        return hashlib.sha256(fila["estado"].encode()).hexdigest()

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict[str, Any],
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        datos = _contenido(contenido)
        fila = _leer(conn, objetivo)
        id_cliente = fila["id_cliente"]
        actual = fila["estado"]
        if datos.estado not in service._TRANSICIONES_CLIENTE.get(actual, set()):
            raise problema(
                409,
                "TRANSICION_INVALIDA",
                "El cambio de estado no está permitido.",
            )
        if datos.estado == "Eliminado":
            service._validar_productos_cliente(conn, id_cliente)

        motivo_historial = f"{datos.motivo} (solicitud {id_solicitud})"
        motivo_db = motivo_historial[:300]
        observaciones = repository.observaciones_cambio(
            actual, datos.estado, motivo_historial
        )
        repository.actualizar_estado_cliente(
            conn, id_cliente, datos.estado, motivo=motivo_db
        )
        repository.insertar_historial_cliente(
            conn,
            id_cliente=id_cliente,
            tipo_operacion="U",
            campo="Estado",
            modificado_por=datos.modificado_por,
            direccion_ip=datos.direccion_ip,
            observaciones=observaciones,
            valor_anterior=actual,
            valor_nuevo=datos.estado,
            id_solicitud=id_solicitud,
        )
        if datos.estado == "Eliminado":
            repository.anonimizar_cliente(
                conn,
                id_cliente,
                fila["tipo_cliente"],
                modificado_por=datos.modificado_por,
                direccion_ip=datos.direccion_ip,
                id_solicitud=id_solicitud,
            )


MANEJADOR_ESTADO = ManejadorEstado()

OPERACION_ESTADO = Operacion(
    CODIGO_ESTADO,
    TIPO_OBJETIVO,
    "cooperativa",
    frozenset({"ADMIN", "ASESOR", "SUPERVISOR"}),
    "clientes:aprobar",
    MANEJADOR_ESTADO,
    tabla_auditada="Clientes.Cliente",
    evento_ejecucion="CLI_ESTADO",
    solicitud_directa=False,
    validar_aprobador=validar_aprobador_estado,
)

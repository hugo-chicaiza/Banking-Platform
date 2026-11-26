"""E5-07: reincorporación de clientes eliminados con aprobación (cola E0-08)."""

import hashlib
from datetime import date
from typing import Annotated, Any

from pydantic import ConfigDict, Field, ValidationError
from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.api.schemas import CamelModel
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.clientes import repository
from app.modules.clientes.schemas import ClienteCreate

CODIGO_REINCORPORACION = "CLI-REINCORPORAR"
TIPO_OBJETIVO = "ClienteReincorporacion"


def objetivo(id_cliente: int) -> Objetivo:
    return Objetivo(TIPO_OBJETIVO, str(id_cliente), None)


class ContenidoReincorporacion(CamelModel):
    model_config = ConfigDict(extra="forbid")

    datos: ClienteCreate
    modificado_por: Annotated[int, Field(gt=0)]
    direccion_ip: str = Field(min_length=1, max_length=45)
    id_agencia: str | None = None


def _contenido(contenido: dict[str, Any]) -> ContenidoReincorporacion:
    try:
        return ContenidoReincorporacion.model_validate(contenido)
    except ValidationError:
        raise problema(
            422,
            "CONTENIDO_INVALIDO",
            "La solicitud de reincorporación no cumple el contrato.",
        ) from None


def _leer(conn: Connection, objetivo: Objetivo) -> dict[str, Any]:
    if not objetivo.id.isdigit() or objetivo.agencia is not None:
        raise problema(422, "OBJETIVO_INVALIDO", "Seleccione el cliente objetivo.")
    # Trae tipo de cliente y de documento (bloquear_cliente no los devuelve).
    fila = repository.bloquear_datos_sensibles(conn, int(objetivo.id))
    if fila is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "No se encontró el cliente.")
    return fila


class ManejadorReincorporacion:
    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan:
        datos = _contenido(contenido)
        fila = _leer(conn, objetivo)
        if fila["estado"] != "Eliminado":
            raise problema(
                409,
                "CLIENTE_NO_ELIMINADO",
                "El cliente no está en estado Eliminado.",
            )
        cliente_datos = datos.datos
        if (
            cliente_datos.tipo_cliente != fila["tipo_cliente"]
            or cliente_datos.tipo_documento != fila["tipo_documento"]
        ):
            raise problema(
                422,
                "DATOS_NO_COINCIDEN",
                "El tipo de cliente y el tipo de documento deben coincidir con los registrados.",
            )
        return Plan(
            datos.model_dump(mode="json", by_alias=True),
            {"estado": "Eliminado"},
            {"estado": "Pendiente"},
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
        if fila["estado"] != "Eliminado":
            raise problema(
                409,
                "CLIENTE_NO_ELIMINADO",
                "El cliente no está en estado Eliminado.",
            )
        cliente_datos = datos.datos
        if (
            cliente_datos.tipo_cliente != fila["tipo_cliente"]
            or cliente_datos.tipo_documento != fila["tipo_documento"]
        ):
            raise problema(
                422,
                "DATOS_NO_COINCIDEN",
                "El tipo de cliente y el tipo de documento deben coincidir con los registrados.",
            )
        id_cliente = int(objetivo.id)

        # 1. Actualización SQL de datos personales y estado a Pendiente
        repository.reincorporar_cliente(
            conn,
            id_cliente,
            cliente_datos,
            id_agencia=datos.id_agencia,
            id_solicitud=id_solicitud,
        )

        # 2. Inserción de nueva dirección principal
        # snake_case: es lo que espera repository.insertar_direccion
        dir_payload = cliente_datos.direccion.model_dump()
        repository.insertar_direccion(
            conn,
            id_cliente,
            dir_payload,
            modificado_por=datos.modificado_por,
            direccion_ip=datos.direccion_ip,
        )

        # 3. Marcar no vigentes evaluaciones de riesgo anteriores
        repository.invalidar_riesgos_cliente(conn, id_cliente)

        # 4. Inserción de historial inmutable sin datos personales
        motivo = f"Reincorporación (solicitud {id_solicitud})"
        observaciones_estado = repository.observaciones_cambio(
            "Eliminado", "Pendiente", motivo
        )
        repository.insertar_historial_cliente(
            conn,
            id_cliente=id_cliente,
            tipo_operacion="U",
            campo="Estado",
            modificado_por=datos.modificado_por,
            direccion_ip=datos.direccion_ip,
            observaciones=observaciones_estado,
            valor_anterior="Eliminado",
            valor_nuevo="Pendiente",
            id_solicitud=id_solicitud,
        )
        observaciones_reinc = repository.observaciones_cambio(
            None, "Datos personales registrados de nuevo", motivo
        )
        repository.insertar_historial_cliente(
            conn,
            id_cliente=id_cliente,
            tipo_operacion="U",
            campo="REINCORPORACION",
            modificado_por=datos.modificado_por,
            direccion_ip=datos.direccion_ip,
            observaciones=observaciones_reinc,
            valor_anterior=None,
            valor_nuevo="Datos personales registrados de nuevo",
            id_solicitud=id_solicitud,
        )


MANEJADOR_REINCORPORACION = ManejadorReincorporacion()

OPERACION_REINCORPORACION = Operacion(
    CODIGO_REINCORPORACION,
    TIPO_OBJETIVO,
    "cooperativa",
    frozenset({"ADMIN", "ASESOR", "SUPERVISOR"}),
    "clientes:aprobar",
    MANEJADOR_REINCORPORACION,
    tabla_auditada="Clientes.Cliente",
    evento_ejecucion="CLI_REINCORPORADO",
    solicitud_directa=False,
)

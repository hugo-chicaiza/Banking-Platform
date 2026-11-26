"""E5-06: evaluación de riesgo aprobada por otra persona (cola E0-08)."""

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.core.database.db import get_engine
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.clientes import repository, service
from app.modules.clientes.habilitacion import activar_si_cumple
from app.modules.clientes.schemas import ContenidoRiesgo
from app.modules.parametros.service import hoy

CODIGO_RIESGO = "CLI-RIESGO"
TIPO_OBJETIVO = "ClienteRiesgo"


def objetivo(id_cliente: int) -> Objetivo:
    return Objetivo(TIPO_OBJETIVO, str(id_cliente), None)


def _contenido(contenido: dict[str, Any]) -> ContenidoRiesgo:
    try:
        return ContenidoRiesgo.model_validate(contenido)
    except ValidationError:
        raise problema(
            422,
            "CONTENIDO_INVALIDO",
            "La propuesta de evaluación de riesgo no cumple el contrato.",
        ) from None


def _leer(conn: Connection, objetivo: Objetivo) -> dict[str, Any]:
    if not objetivo.id.isdigit() or objetivo.agencia is not None:
        raise problema(422, "OBJETIVO_INVALIDO", "Seleccione el cliente objetivo.")
    id_cliente = int(objetivo.id)
    fila = repository.bloquear_cliente(conn, id_cliente)
    if fila is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "No se encontró el cliente.")
    service._validar_cliente_no_eliminado(fila, id_cliente)
    return fila


def validar_aprobador_riesgo(objetivo: Objetivo, id_interno: int) -> None:
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
                "Quien registró al cliente no puede aprobar su evaluación de riesgo.",
            )


class EvaluacionRiesgo:
    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan:
        datos = _contenido(contenido)
        fila = _leer(conn, objetivo)
        service.validar_datos_riesgo(conn, datos, hoy)

        vigentes = repository.listar_evaluaciones_riesgo(
            conn, fila["id_cliente"], solo_vigente=True
        )
        if vigentes:
            v = vigentes[0]
            antes = {
                "nivel": v["nivel_riesgo_laft"],
                "pep": v["es_pep"],
                "resultado": v["resultado_evaluacion"],
                "vigenteHasta": (
                    v["vigente_hasta"].isoformat()
                    if v.get("vigente_hasta") is not None
                    else None
                ),
            }
        else:
            antes = {}

        despues = datos.model_dump(mode="json", by_alias=True)
        return Plan(
            despues,
            antes,
            despues,
            self.version(conn, objetivo),
        )

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        fila = _leer(conn, objetivo)
        vigentes = repository.listar_evaluaciones_riesgo(
            conn, fila["id_cliente"], solo_vigente=True
        )
        id_vigente = vigentes[0]["id_evaluacion"] if vigentes else None
        huella = {"id_evaluacion": id_vigente, "estado": fila["estado"]}
        return hashlib.sha256(json.dumps(huella, sort_keys=True).encode()).hexdigest()

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
        fecha_evaluacion = datetime.now(UTC)
        fecha_operativa = hoy()
        meses_vigencia = service.validar_datos_riesgo(conn, datos, fecha_operativa)

        repository.insertar_evaluacion_riesgo(
            conn,
            fila["id_cliente"],
            datos.model_dump(),
            evaluador=datos.evaluador,
            direccion_ip=datos.direccion_ip,
            fecha_evaluacion=fecha_evaluacion,
            fecha_operativa=fecha_operativa,
            meses_vigencia=meses_vigencia,
            id_solicitud=id_solicitud,
        )
        activar_si_cumple(
            conn,
            fila["id_cliente"],
            fecha_operativa,
            actor=datos.evaluador,
            ip=datos.direccion_ip,
            solicitud_en_aplicacion=id_solicitud,
        )


OPERACION_RIESGO = Operacion(
    CODIGO_RIESGO,
    TIPO_OBJETIVO,
    "cooperativa",
    frozenset({"ADMIN", "ASESOR", "SUPERVISOR"}),
    "clientes:aprobar",
    EvaluacionRiesgo(),
    tabla_auditada="Clientes.RiesgoCliente",
    evento_ejecucion="CLI_RIESGO_EVALUADO",
    solicitud_directa=False,
    validar_aprobador=validar_aprobador_riesgo,
)

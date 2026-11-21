"""Cambio de tarifa E1-12 en la cola E0-08."""

import hashlib
import json
from datetime import date

from pydantic import ValidationError
from sqlalchemy import Connection

from app.core.api.errors import problema
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.parametros import repository as repo
from app.modules.parametros.schemas import Entrada, Valor


class PropuestaTarifa(Entrada):
    valor: Valor | None = None
    vigencia_desde: date


def _estado(conn: Connection, objetivo: Objetivo) -> tuple[int, dict, list[dict]]:
    if (
        objetivo.agencia is not None
        or not objetivo.id.isascii()
        or not objetivo.id.isdecimal()
    ):
        raise problema(422, "OBJETIVO_INVALIDO", "La comisión es un objetivo global.")
    id_ = int(objetivo.id)
    if not 1 <= id_ <= 2147483647:
        raise problema(
            422, "OBJETIVO_INVALIDO", "El identificador de comisión no es válido."
        )
    repo.bloquear_comisiones(conn)
    comision = repo.obtener_comision(conn, id_)
    if comision is None:
        raise problema(404, "COMISION_NO_ENCONTRADA", "La comisión no existe.")
    return id_, comision, repo.versiones_comision(conn, id_)


def _huella(comision: dict, versiones: list[dict]) -> str:
    # El valor de presentación depende del día; la huella depende de las filas persistidas.
    datos = {k: v for k, v in comision.items() if k != "valor"}
    return hashlib.sha256(
        json.dumps([datos, versiones], sort_keys=True, default=str).encode()
    ).hexdigest()


def _validar(
    comision: dict,
    versiones: list[dict],
    contenido: dict,
    hoy: date,
    *,
    aprobando: bool = False,
):
    try:
        datos = PropuestaTarifa.model_validate(contenido)
    except ValidationError:
        raise problema(
            422, "CONTENIDO_INVALIDO", "La propuesta de tarifa no es válida."
        ) from None
    if comision["estado"] != "A":
        raise problema(409, "COMISION_INACTIVA", "La comisión no está activa.")
    if not versiones:
        raise problema(
            409, "TARIFA_SIN_VERSION", "La comisión no tiene una tarifa inicial."
        )
    if datos.vigencia_desde <= hoy:
        raise problema(
            409 if aprobando else 422,
            "VIGENCIA_TARIFA_VENCIDA" if aprobando else "VIGENCIA_TARIFA_NO_FUTURA",
            "La fecha efectiva debe ser posterior al día de aprobación."
            if aprobando
            else "La fecha efectiva propuesta debe ser posterior a hoy.",
        )
    anterior = versiones[-1]
    if datos.vigencia_desde <= anterior["desde"] or (
        anterior["hasta"] is not None and datos.vigencia_desde >= anterior["hasta"]
    ):
        raise problema(
            409,
            "COMISION_VIGENCIA_SOLAPADA",
            "La nueva fecha debe dividir la última vigencia sin invadir otra versión.",
        )
    valor = anterior["valor"] if datos.valor is None else datos.valor
    if comision["tipo_calculo"] == "Porcentaje" and valor > 100:
        raise problema(
            422, "VALOR_FUERA_DE_RANGO", "El porcentaje debe estar entre 0 y 100."
        )
    return anterior, valor, datos.vigencia_desde


class TarifaComision:
    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict, hoy: date
    ) -> Plan:
        id_, comision, versiones = _estado(conn, objetivo)
        anterior, valor, desde = _validar(comision, versiones, contenido, hoy)
        propuesta = {"valor": str(valor), "vigenciaDesde": desde.isoformat()}
        antes = {
            "idComision": id_,
            "idVersion": anterior["id_version"],
            "valor": str(anterior["valor"]),
            "vigenciaDesde": anterior["desde"].isoformat(),
            "vigenciaHasta": anterior["hasta"].isoformat()
            if anterior["hasta"]
            else None,
        }
        return Plan(
            propuesta,
            antes,
            {**propuesta, "idComision": id_, "vigenciaHasta": antes["vigenciaHasta"]},
            _huella(comision, versiones),
        )

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        _, comision, versiones = _estado(conn, objetivo)
        return _huella(comision, versiones)

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict,
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        from app.modules.parametros.service import hoy

        id_, comision, versiones = _estado(conn, objetivo)
        anterior, valor, desde = _validar(
            comision, versiones, contenido, hoy(), aprobando=True
        )
        repo.versionar_tarifa(conn, id_, anterior, desde, valor, id_solicitud)


OPERACION_TARIFA = Operacion(
    "PAR-COMISION",
    "Comision",
    "cooperativa",
    frozenset({"ADMIN"}),
    "parametros:aprobar",
    TarifaComision(),
    tabla_auditada="Transacciones.ComisionValor",
    solicitud_directa=False,
)

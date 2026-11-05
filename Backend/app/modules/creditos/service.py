import logging
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.modules.contabilidad.service import ahora_ecuador
from app.modules.creditos import amortizacion, repository
from app.modules.creditos.schemas import (
    CondicionesCredito,
    RubroCredito,
    Simulacion,
    SimulacionRequest,
)

log = logging.getLogger(__name__)


def _hoy() -> date:
    """Fecha de hoy en Ecuador (UTC-5); sirve para decidir qué tasas están vigentes."""
    return ahora_ecuador().date()


def _monto_en_rango(tasa: dict[str, Any], monto: Decimal) -> bool:
    minimo, maximo = tasa["monto_minimo"], tasa["monto_maximo"]
    return (minimo is None or monto >= minimo) and (maximo is None or monto <= maximo)


def _tasa_unica(candidatas: list[dict[str, Any]]) -> dict[str, Any]:
    """Dos tasas vigentes para la misma consulta es un error de datos, no del cliente."""
    if len(candidatas) > 1:
        # Alerta operativa: hay que corregir las vigencias en Credito.TasaInteres
        log.error(
            "ALERTA más de una tasa vigente para el mismo tipo y monto (DB 55103)"
        )
        raise problema(
            500,
            "TASA_VIGENTE_DUPLICADA",
            "Hay más de una tasa vigente para esta consulta.",
        )
    return candidatas[0]


def _sin_tasa_vigente():
    return problema(
        404,
        "TASA_NO_VIGENTE",
        "No hay una tasa vigente para el tipo de crédito, monto y plazo indicados.",
    )


def obtener_condiciones(
    conn: Connection,
    id_tipo_credito: int,
    monto: Decimal | None = None,
    plazo_meses: int | None = None,
    hoy: date | None = None,
) -> CondicionesCredito:
    """CRE-01: tasa, plazo máximo, seguros e impuestos vigentes de un tipo de crédito.

    Raises:
        HTTPException 404 TASA_NO_VIGENTE
        HTTPException 500 TASA_VIGENTE_DUPLICADA
    """
    hoy = hoy or _hoy()
    tasas = repository.tasas_vigentes(conn, id_tipo_credito, hoy)
    candidatas = [
        t
        for t in tasas
        if (monto is None or _monto_en_rango(t, monto))
        and (plazo_meses is None or plazo_meses <= t["plazo_maximo_meses"])
    ]
    if not candidatas:
        raise _sin_tasa_vigente()
    tasa = _tasa_unica(candidatas)
    return CondicionesCredito(
        **tasa,
        seguros=[
            RubroCredito(**r)
            for r in repository.seguros_activos(conn, id_tipo_credito, hoy)
        ],
        impuestos=[
            RubroCredito(**r)
            for r in repository.impuestos_activos(conn, id_tipo_credito, hoy)
        ],
    )


def simular(
    conn: Connection, datos: SimulacionRequest, hoy: date | None = None
) -> Simulacion:
    """CRE-02: tabla de amortización con seguros e impuestos. No guarda nada.

    Raises:
        HTTPException 404 TASA_NO_VIGENTE (el tipo no tiene ninguna tasa vigente)
        HTTPException 422 MONTO_FUERA_DE_RANGO
        HTTPException 422 PLAZO_SUPERA_MAXIMO
        HTTPException 500 TASA_VIGENTE_DUPLICADA
    """
    hoy = hoy or _hoy()
    tasas = repository.tasas_vigentes(conn, datos.id_tipo_credito, hoy)
    if not tasas:
        raise _sin_tasa_vigente()
    por_monto = [t for t in tasas if _monto_en_rango(t, datos.monto)]
    if not por_monto:
        raise problema(
            422,
            "MONTO_FUERA_DE_RANGO",
            "El monto está fuera del rango de la tasa vigente.",
        )
    tasa = _tasa_unica(por_monto)
    if datos.plazo_meses > tasa["plazo_maximo_meses"]:
        raise problema(
            422,
            "PLAZO_SUPERA_MAXIMO",
            "El plazo supera el máximo de la tasa vigente.",
        )

    plan = amortizacion.calcular_plan(
        monto=datos.monto,
        plazo_meses=datos.plazo_meses,
        tasa_nominal_anual=tasa["tasa_nominal_anual"],
        sistema=datos.sistema_amortizacion,
        primer_vencimiento=datos.fecha_primer_vencimiento
        or amortizacion.sumar_meses(hoy, 1),
        seguros=repository.seguros_activos(conn, datos.id_tipo_credito, hoy),
        impuestos=repository.impuestos_activos(conn, datos.id_tipo_credito, hoy),
    )
    return Simulacion(
        tasa_nominal_anual=tasa["tasa_nominal_anual"],
        cuota_referencial=plan[0].valor,
        total_intereses=sum((c.interes for c in plan), Decimal(0)),
        total_seguros=sum((c.total_seguros for c in plan), Decimal(0)),
        total_impuestos=sum((c.total_impuestos for c in plan), Decimal(0)),
        costo_total=sum((c.valor for c in plan), Decimal(0)),
        plan=plan,
    )

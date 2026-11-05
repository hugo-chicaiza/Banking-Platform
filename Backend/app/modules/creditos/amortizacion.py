"""Cálculo puro de la tabla de amortización (CRE-02). No toca la base de datos.

Supuestos de negocio (confirmar con el equipo):
- Tasa mensual = tasa nominal anual / 12, sobre el saldo pendiente.
- Seguro "Porcentaje": valor% del saldo inicial de cada cuota. "Fijo": valor por cuota.
- Impuesto "Porcentaje": valor% del monto del crédito, cobrado una vez y repartido
  en partes iguales entre las cuotas. "Fijo": valor total repartido igual.
- Todo se redondea a 2 decimales (mitad hacia arriba). La última cuota absorbe la
  diferencia de redondeo para que el saldo final sea exactamente 0.
"""

import calendar
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.creditos.schemas import CuotaSimulada, SistemaAmortizacion

_CENTAVO = Decimal("0.01")
_CIEN = Decimal(100)
_MESES_ANIO = Decimal(12)
_PORCENTAJE = "porcentaje"


def redondear(valor: Decimal) -> Decimal:
    return valor.quantize(_CENTAVO, rounding=ROUND_HALF_UP)


def sumar_meses(base: date, meses: int) -> date:
    """Suma meses calendario; si el día no existe, usa el último del mes (31-ene → 28-feb)."""
    indice = base.month - 1 + meses
    anio = base.year + indice // 12
    mes = indice % 12 + 1
    return date(anio, mes, min(base.day, calendar.monthrange(anio, mes)[1]))


def _cuota_francesa(monto: Decimal, plazo: int, tasa_mensual: Decimal) -> Decimal:
    if tasa_mensual == 0:
        return monto / plazo
    factor = (1 + tasa_mensual) ** plazo
    return monto * tasa_mensual * factor / (factor - 1)


def _es_porcentaje(rubro: dict[str, Any]) -> bool:
    return str(rubro["tipo_calculo"]).strip().lower() == _PORCENTAJE


def _seguro_por_cuota(rubro: dict[str, Any], saldo_inicial: Decimal) -> Decimal:
    valor = Decimal(rubro["valor"])
    if _es_porcentaje(rubro):
        return redondear(saldo_inicial * valor / _CIEN)
    return redondear(valor)


def _impuesto_total(rubro: dict[str, Any], monto: Decimal) -> Decimal:
    valor = Decimal(rubro["valor"])
    if _es_porcentaje(rubro):
        return redondear(monto * valor / _CIEN)
    return redondear(valor)


def calcular_plan(
    *,
    monto: Decimal,
    plazo_meses: int,
    tasa_nominal_anual: Decimal,
    sistema: SistemaAmortizacion,
    primer_vencimiento: date,
    seguros: Sequence[dict[str, Any]],
    impuestos: Sequence[dict[str, Any]],
) -> list[CuotaSimulada]:
    tasa_mensual = tasa_nominal_anual / _MESES_ANIO
    cuota_francesa = (
        redondear(_cuota_francesa(monto, plazo_meses, tasa_mensual))
        if sistema is SistemaAmortizacion.FRANCES
        else Decimal(0)
    )
    capital_aleman = redondear(monto / plazo_meses)

    impuesto_total = sum((_impuesto_total(r, monto) for r in impuestos), Decimal(0))
    impuesto_por_cuota = redondear(impuesto_total / plazo_meses)

    plan: list[CuotaSimulada] = []
    saldo = monto
    impuesto_acumulado = Decimal(0)
    for numero in range(1, plazo_meses + 1):
        ultima = numero == plazo_meses
        interes = redondear(saldo * tasa_mensual)
        if ultima:
            capital = saldo
        elif sistema is SistemaAmortizacion.FRANCES:
            capital = min(cuota_francesa - interes, saldo)
        else:
            capital = min(capital_aleman, saldo)
        total_seguros = sum((_seguro_por_cuota(r, saldo) for r in seguros), Decimal(0))
        total_impuestos = (
            impuesto_total - impuesto_acumulado if ultima else impuesto_por_cuota
        )
        impuesto_acumulado += total_impuestos
        saldo_final = saldo - capital
        plan.append(
            CuotaSimulada(
                numero=numero,
                vencimiento=sumar_meses(primer_vencimiento, numero - 1),
                saldo_inicial=saldo,
                capital=capital,
                interes=interes,
                total_seguros=total_seguros,
                total_impuestos=total_impuestos,
                valor=capital + interes + total_seguros + total_impuestos,
                saldo_final=saldo_final,
            )
        )
        saldo = saldo_final
    return plan

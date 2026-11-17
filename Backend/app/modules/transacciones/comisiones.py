"""Cálculo puro de comisiones con una regla de exoneración ya seleccionada."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_CENTAVO = Decimal("0.01")
_CIEN = Decimal(100)


@dataclass(frozen=True)
class ReglaExoneracion:
    id_exoneracion: int
    porcentaje_exonerado: Decimal
    operaciones_gratis_mes: int | None = None

    def __post_init__(self) -> None:
        if (
            not self.porcentaje_exonerado.is_finite()
            or not 0 <= self.porcentaje_exonerado <= _CIEN
        ):
            raise ValueError("El porcentaje exonerado debe estar entre 0 y 100")
        if self.operaciones_gratis_mes is not None and (
            type(self.operaciones_gratis_mes) is not int
            or self.operaciones_gratis_mes < 0
        ):
            raise ValueError("El cupo mensual debe ser un entero no negativo")


def calcular_comision(
    monto_base: Decimal | None,
    regla: ReglaExoneracion | None,
    operaciones_previas_mes: int,
) -> tuple[Decimal, int | None]:
    """Devuelve (monto a cobrar, ID de la regla aplicada).

    None como monto indica que no hay comisión configurada. El llamador selecciona
    la regla vigente y cuenta las operaciones anteriores del mes, sin incluir la
    actual. Un cupo None permite aplicar el porcentaje sin límite mensual; un cupo
    agotado cobra el monto completo. El importe final se redondea una sola vez.
    """
    if type(operaciones_previas_mes) is not int or operaciones_previas_mes < 0:
        raise ValueError("Las operaciones previas deben ser un entero no negativo")
    if monto_base is None:
        return Decimal("0.00"), None
    if not monto_base.is_finite() or monto_base < 0:
        raise ValueError("El monto base debe ser finito y no negativo")

    id_regla = None
    monto = monto_base
    if (
        regla is not None
        and monto_base > 0
        and regla.porcentaje_exonerado > 0
        and (
            regla.operaciones_gratis_mes is None
            or operaciones_previas_mes < regla.operaciones_gratis_mes
        )
    ):
        monto = monto_base * (_CIEN - regla.porcentaje_exonerado) / _CIEN
        id_regla = regla.id_exoneracion

    return monto.quantize(_CENTAVO, rounding=ROUND_HALF_UP), id_regla

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Literal

_CENTAVO = Decimal("0.01")
_MAXIMO_MONTO = Decimal("9999999999999999.99")
_MAX_SOLICITUDES = 10000
_CAUSAS_ADMITIDAS = {"RetiroVoluntario", "Fallecimiento"}
TIPO_CUENTA_CERTIFICADO = "CERTIFICADO_APORTACION"


def es_cuenta_certificado(tipo_cuenta: object) -> bool:
    return (
        isinstance(tipo_cuenta, str)
        and tipo_cuenta.strip().upper() == TIPO_CUENTA_CERTIFICADO
    )


@dataclass(frozen=True)
class SolicitudRedencion:
    id_solicitud: int
    causa: Literal["RetiroVoluntario", "Fallecimiento"]
    monto_neto: Decimal


@dataclass(frozen=True)
class AsignacionRedencion:
    id_solicitud: int
    monto_pagado: Decimal
    monto_en_cola: Decimal


def asignar_tope_anual(
    solicitudes: Sequence[SolicitudRedencion], limite_disponible: Decimal
) -> list[AsignacionRedencion]:
    """Distribuye el tope entre retiros voluntarios sin perder centavos."""
    _validar_monto(limite_disponible, "limite_disponible")
    if len(solicitudes) > _MAX_SOLICITUDES:
        raise ValueError("El lote excede el maximo de solicitudes admitido.")
    if not solicitudes:
        return []

    ids: set[int] = set()
    for solicitud in solicitudes:
        if type(solicitud.id_solicitud) is not int or solicitud.id_solicitud <= 0:
            raise ValueError("id_solicitud debe ser un entero positivo.")
        if solicitud.id_solicitud in ids:
            raise ValueError("Las solicitudes deben tener identificadores unicos.")
        ids.add(solicitud.id_solicitud)
        if (
            not isinstance(solicitud.causa, str)
            or solicitud.causa not in _CAUSAS_ADMITIDAS
        ):
            raise ValueError("La causa de redencion no esta admitida.")
        _validar_monto(solicitud.monto_neto, "monto_neto")

    voluntarias = [
        solicitud for solicitud in solicitudes if solicitud.causa == "RetiroVoluntario"
    ]
    total_voluntario = sum(
        (solicitud.monto_neto for solicitud in voluntarias), start=Decimal("0.00")
    )
    pagado_por_id = {
        solicitud.id_solicitud: solicitud.monto_neto
        for solicitud in solicitudes
        if solicitud.causa == "Fallecimiento"
    }

    presupuesto = min(limite_disponible, total_voluntario)
    if total_voluntario > 0 and presupuesto > 0:
        with localcontext() as contexto:
            contexto.prec = 50
            proporciones = {
                solicitud.id_solicitud: (
                    presupuesto * solicitud.monto_neto / total_voluntario
                )
                for solicitud in voluntarias
            }
            pagado_por_id.update(
                {
                    id_solicitud: monto.quantize(_CENTAVO, rounding=ROUND_DOWN)
                    for id_solicitud, monto in proporciones.items()
                }
            )
            centavos_restantes = int(
                (
                    presupuesto
                    - sum(
                        (
                            pagado_por_id[solicitud.id_solicitud]
                            for solicitud in voluntarias
                        ),
                        start=Decimal("0.00"),
                    )
                )
                / _CENTAVO
            )
            orden_residuo = sorted(
                voluntarias,
                key=lambda solicitud: (
                    -(
                        proporciones[solicitud.id_solicitud]
                        - pagado_por_id[solicitud.id_solicitud]
                    ),
                    solicitud.id_solicitud,
                ),
            )
            for solicitud in orden_residuo[:centavos_restantes]:
                pagado_por_id[solicitud.id_solicitud] += _CENTAVO

    return [
        AsignacionRedencion(
            id_solicitud=solicitud.id_solicitud,
            monto_pagado=pagado_por_id.get(solicitud.id_solicitud, Decimal("0.00")),
            monto_en_cola=(
                solicitud.monto_neto
                - pagado_por_id.get(solicitud.id_solicitud, Decimal("0.00"))
            ),
        )
        for solicitud in solicitudes
    ]


def _validar_monto(monto: Decimal, campo: str) -> None:
    if (
        not isinstance(monto, Decimal)
        or not monto.is_finite()
        or monto < 0
        or monto > _MAXIMO_MONTO
        or monto != monto.quantize(_CENTAVO)
    ):
        raise ValueError(
            f"{campo} debe ser un monto no negativo con maximo dos decimales."
        )

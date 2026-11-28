from decimal import Decimal

import pytest

from app.modules.cuentas.certificados import (
    SolicitudRedencion,
    asignar_tope_anual,
)


def test_asigna_tope_proporcionalmente_y_conserva_centavos() -> None:
    solicitudes = [
        SolicitudRedencion(1, "RetiroVoluntario", Decimal("100.00")),
        SolicitudRedencion(2, "RetiroVoluntario", Decimal("200.00")),
        SolicitudRedencion(3, "RetiroVoluntario", Decimal("300.00")),
    ]

    resultado = asignar_tope_anual(solicitudes, Decimal("100.00"))

    assert [fila.monto_pagado for fila in resultado] == [
        Decimal("16.67"),
        Decimal("33.33"),
        Decimal("50.00"),
    ]
    assert sum((fila.monto_pagado for fila in resultado), Decimal("0.00")) == Decimal(
        "100.00"
    )
    assert sum(
        (fila.monto_pagado + fila.monto_en_cola for fila in resultado),
        Decimal("0.00"),
    ) == Decimal("600.00")


def test_fallecimiento_no_consumo_tope_anual_de_retiro() -> None:
    solicitudes = [
        SolicitudRedencion(1, "Fallecimiento", Decimal("50.00")),
        SolicitudRedencion(2, "RetiroVoluntario", Decimal("100.00")),
    ]

    resultado = asignar_tope_anual(solicitudes, Decimal("30.00"))

    assert resultado[0].monto_pagado == Decimal("50.00")
    assert resultado[0].monto_en_cola == Decimal("0.00")
    assert resultado[1].monto_pagado == Decimal("30.00")
    assert resultado[1].monto_en_cola == Decimal("70.00")


def test_limite_suficiente_paga_solicitudes_voluntarias_completas() -> None:
    resultado = asignar_tope_anual(
        [SolicitudRedencion(1, "RetiroVoluntario", Decimal("25.10"))],
        Decimal("100.00"),
    )

    assert resultado[0].monto_pagado == Decimal("25.10")
    assert resultado[0].monto_en_cola == Decimal("0.00")


def test_reparto_de_residuos_es_independiente_del_orden_de_entrada() -> None:
    solicitudes = [
        SolicitudRedencion(8, "RetiroVoluntario", Decimal("1.00")),
        SolicitudRedencion(3, "RetiroVoluntario", Decimal("1.00")),
    ]

    resultado = asignar_tope_anual(solicitudes, Decimal("0.01"))
    invertido = asignar_tope_anual(list(reversed(solicitudes)), Decimal("0.01"))

    asignaciones = {fila.id_solicitud: fila.monto_pagado for fila in resultado}
    assert asignaciones == {
        3: Decimal("0.01"),
        8: Decimal("0.00"),
    }
    assert {fila.id_solicitud: fila.monto_pagado for fila in invertido} == asignaciones


@pytest.mark.parametrize(
    ("solicitudes", "limite"),
    [
        (
            [SolicitudRedencion(1, "RetiroVoluntario", Decimal("-1.00"))],
            Decimal("1.00"),
        ),
        (
            [SolicitudRedencion(1, "RetiroVoluntario", Decimal("1.001"))],
            Decimal("1.00"),
        ),
        ([SolicitudRedencion(1, "RetiroVoluntario", Decimal("NaN"))], Decimal("1.00")),
        (
            [SolicitudRedencion(1, "RetiroVoluntario", Decimal("1.00"))],
            Decimal("-1.00"),
        ),
        (
            [
                SolicitudRedencion(1, "RetiroVoluntario", Decimal("1.00")),
                SolicitudRedencion(1, "RetiroVoluntario", Decimal("2.00")),
            ],
            Decimal("1.00"),
        ),
    ],
)
def test_rechaza_montos_y_solicitudes_invalidos(solicitudes, limite) -> None:
    with pytest.raises(ValueError):
        asignar_tope_anual(solicitudes, limite)


def test_rechaza_importes_que_no_sean_decimal() -> None:
    solicitud = SolicitudRedencion(1, "RetiroVoluntario", 1.0)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        asignar_tope_anual([solicitud], Decimal("1.00"))

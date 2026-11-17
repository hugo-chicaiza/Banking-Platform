from decimal import Decimal

import pytest

from app.modules.transacciones.comisiones import ReglaExoneracion, calcular_comision


def test_sin_comision_configurada():
    assert calcular_comision(None, None, 0) == (Decimal("0.00"), None)


def test_exoneracion_total_devuelve_regla():
    regla = ReglaExoneracion(17, Decimal(100))
    assert calcular_comision(Decimal("1.25"), regla, 0) == (Decimal("0.00"), 17)


@pytest.mark.parametrize(
    ("previas", "monto", "id_regla"),
    [(0, "1.25", 17), (2, "1.25", 17), (3, "2.50", None), (4, "2.50", None)],
)
def test_cupo_mensual(previas, monto, id_regla):
    regla = ReglaExoneracion(17, Decimal(50), operaciones_gratis_mes=3)
    assert calcular_comision(Decimal("2.50"), regla, previas) == (
        Decimal(monto),
        id_regla,
    )


@pytest.mark.parametrize("previas", [0, 2, 3])
def test_tres_operaciones_gratis_tercera_gratis_y_cuarta_cobra(previas):
    regla = ReglaExoneracion(17, Decimal(100), operaciones_gratis_mes=3)
    esperado = (Decimal("0.00"), 17) if previas < 3 else (Decimal("2.50"), None)
    assert calcular_comision(Decimal("2.50"), regla, previas) == esperado


@pytest.mark.parametrize("porcentaje", ["-0.01", "100.01", "NaN", "Infinity"])
def test_rechaza_porcentaje_invalido(porcentaje):
    with pytest.raises(ValueError, match="porcentaje"):
        ReglaExoneracion(17, Decimal(porcentaje))


def test_redondea_monto_a_cobrar_half_up():
    regla = ReglaExoneracion(17, Decimal(50))
    assert calcular_comision(Decimal("0.05"), regla, 0) == (Decimal("0.03"), 17)


def test_sin_regla_cobra_comision_completa_redondeada():
    assert calcular_comision(Decimal("1.005"), None, 0) == (Decimal("1.01"), None)


def test_porcentaje_cero_no_aplica_exoneracion():
    regla = ReglaExoneracion(17, Decimal(0))
    assert calcular_comision(Decimal("1.25"), regla, 0) == (Decimal("1.25"), None)


def test_cupo_cero_no_aplica_exoneracion():
    regla = ReglaExoneracion(17, Decimal(100), operaciones_gratis_mes=0)
    assert calcular_comision(Decimal("1.25"), regla, 0) == (Decimal("1.25"), None)


@pytest.mark.parametrize("monto", [None, Decimal(0)])
def test_sin_monto_no_registra_regla(monto):
    regla = ReglaExoneracion(17, Decimal(100))
    assert calcular_comision(monto, regla, 0) == (Decimal("0.00"), None)


@pytest.mark.parametrize("monto", ["-0.01", "NaN", "Infinity"])
def test_rechaza_monto_invalido(monto):
    with pytest.raises(ValueError, match="monto base"):
        calcular_comision(Decimal(monto), None, 0)


@pytest.mark.parametrize("cantidad", [-1, 1.5, True])
def test_rechaza_contador_invalido(cantidad):
    with pytest.raises(ValueError, match="operaciones previas"):
        calcular_comision(Decimal(1), None, cantidad)


@pytest.mark.parametrize("cantidad", [-1, 1.5, True])
def test_rechaza_cupo_invalido(cantidad):
    with pytest.raises(ValueError, match="cupo mensual"):
        ReglaExoneracion(17, Decimal(100), operaciones_gratis_mes=cantidad)

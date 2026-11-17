from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.modules.contabilidad import repository
from app.modules.contabilidad.plantillas import (
    Linea,
    Simulacion,
    simular,
    validar_lineas,
)


def test_rechaza_descuadre_por_base():
    lineas = [
        Linea(lado="DEBITO", origen="FIJA", cuenta=1, base="PRINCIPAL"),
        Linea(lado="CREDITO", origen="FIJA", cuenta=2, base="COMISION"),
    ]
    with pytest.raises(HTTPException) as error:
        validar_lineas(Mock(), lineas)
    assert isinstance(error.value.detail, dict)
    assert error.value.detail.get("code") == "PLANTILLA_NO_CUADRA"


def test_simulacion_comparte_resolvedor_sin_escrituras(monkeypatch):
    conn = Mock()
    monkeypatch.setattr(
        repository,
        "cuenta_para_plantilla",
        Mock(
            return_value={
                "Estado": True,
                "EsImputable": True,
                "CodigoCuenta": "11010510",
            }
        ),
    )
    datos = Simulacion(
        lineas=[
            Linea(lado="DEBITO", origen="FIJA", cuenta=1, base="PRINCIPAL"),
            Linea(lado="CREDITO", origen="FIJA", cuenta=2, base="PRINCIPAL"),
        ],
        montos={"PRINCIPAL": Decimal("100.00")},
    )
    resultado = simular(conn, datos)
    assert resultado["total"] == Decimal(100)
    assert len(resultado["lineas"]) == 2
    conn.execute.assert_not_called()


def test_simulacion_resuelve_comision_sin_rol_y_sin_escrituras(monkeypatch):
    conn = Mock()
    monkeypatch.setattr(
        repository,
        "cuenta_para_plantilla",
        Mock(
            return_value={
                "Estado": True,
                "EsImputable": True,
                "CodigoCuenta": "11010510",
            }
        ),
    )
    datos = Simulacion(
        lineas=[
            Linea(lado="DEBITO", origen="PRODUCTO", rol="CAPITAL", base="COMISION"),
            Linea(lado="CREDITO", origen="COMISION", base="COMISION"),
        ],
        producto={"CAPITAL": 1},
        comision=2,
        montos={"COMISION": Decimal("2.50")},
    )
    resultado = simular(conn, datos)
    assert resultado["total"] == Decimal("2.50")
    assert [linea["cuenta"] for linea in resultado["lineas"]] == [1, 2]
    assert conn.execute.call_count == 1
    assert str(conn.execute.call_args.args[0]).lstrip().upper().startswith("SELECT")

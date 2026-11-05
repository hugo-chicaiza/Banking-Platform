from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.modules.atm.service import validar_terminal


def atm_valido():
    return {
        "id_atm": 1,
        "codigo_atm": "ATM00001",
        "tipo_terminal": "ATM",
        "estado_atm": "A",
        "estado_canal": "A",
        "requiere_tarjeta": True,
        "requiere_pin": True,
        "requiere_terminal": True,
    }


def test_atm_activo():
    with patch(
        "app.modules.atm.service.repository.obtener_atm",
        return_value=atm_valido(),
    ):
        resultado = validar_terminal(None, "ATM00001")

    assert resultado["id_atm"] == 1


@pytest.mark.parametrize(
    "campo, valor",
    [
        ("estado_atm", "I"),
        ("estado_atm", "M"),
        ("estado_canal", "I"),
        ("tipo_terminal", "POS"),
        ("requiere_tarjeta", False),
        ("requiere_pin", False),
        ("requiere_terminal", False),
    ],
)
def test_atm_no_disponible(campo, valor):
    datos = atm_valido()
    datos[campo] = valor

    with patch(
        "app.modules.atm.service.repository.obtener_atm",
        return_value=datos,
    ):
        with pytest.raises(HTTPException) as error:
            validar_terminal(None, "ATM00001")

    assert error.value.status_code == 409


def test_atm_inexistente():
    with patch(
        "app.modules.atm.service.repository.obtener_atm",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as error:
            validar_terminal(None, "ATM99999")

    assert error.value.status_code == 409

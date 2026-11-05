from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.atm import service
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
        resultado = validar_terminal(MagicMock(), "ATM00001")

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

    with (
        patch(
            "app.modules.atm.service.repository.obtener_atm",
            return_value=datos,
        ),
        pytest.raises(HTTPException) as error,
    ):
        validar_terminal(MagicMock(), "ATM00001")

    assert error.value.status_code == 409


def test_atm_inexistente():
    with (
        patch(
            "app.modules.atm.service.repository.obtener_atm",
            return_value=None,
        ),
        pytest.raises(HTTPException) as error,
    ):
        validar_terminal(MagicMock(), "ATM99999")

    assert error.value.status_code == 409


def test_validar_tarjeta_activa():
    tarjeta = {
        "id_tarjeta": 1,
        "estado_tarjeta": "Activa",
        "fecha_expiracion": date.today() + timedelta(days=30),
        "pin_asignado": True,
    }

    with patch(
        "app.modules.atm.service.repository.obtener_tarjeta",
        return_value=tarjeta,
    ):
        resultado = service.validar_tarjeta(MagicMock(), 1)

    assert resultado == tarjeta


@pytest.mark.parametrize(
    ("estado", "pin_asignado", "dias_vigencia", "codigo_esperado"),
    [
        ("Bloqueada", True, 30, "TARJETA_NO_DISPONIBLE"),
        ("Vencida", True, -1, "TARJETA_NO_DISPONIBLE"),
        ("Activa", True, -1, "TARJETA_NO_DISPONIBLE"),
        ("Activa", False, 30, "PIN_NO_CONFIGURADO"),
    ],
)
def test_validar_tarjeta_rechazada(
    estado, pin_asignado, dias_vigencia, codigo_esperado
):
    tarjeta = {
        "estado_tarjeta": estado,
        "fecha_expiracion": date.today() + timedelta(days=dias_vigencia),
        "pin_asignado": pin_asignado,
    }

    with (
        patch(
            "app.modules.atm.service.repository.obtener_tarjeta",
            return_value=tarjeta,
        ),
        pytest.raises(HTTPException) as error,
    ):
        service.validar_tarjeta(MagicMock(), 1)

    assert error.value.status_code == 409
    assert codigo_esperado in str(error.value.detail)


def test_validar_tarjeta_inexistente():
    with (
        patch(
            "app.modules.atm.service.repository.obtener_tarjeta",
            return_value=None,
        ),
        pytest.raises(HTTPException) as error,
    ):
        service.validar_tarjeta(MagicMock(), 999)

    assert error.value.status_code == 409

"""Regresiones de formato y espacios numericos; sin SQL ni autenticacion simulada."""

from typing import cast

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.productos.numeracion_formato import (
    formar_numero,
    formatos_intersectan,
    verificador,
)
from app.modules.productos.numeracion_schemas import ReglaEntrada


def test_ahorro_conserva_el_formato_de_doce_digitos():
    assert formar_numero(ReglaEntrada(prefijo="2200"), 15, "001") == "220000000015"


@pytest.mark.parametrize("secuencia", [0, -1, 100000000])
def test_agotamiento_no_genera_un_numero_mas_largo(secuencia):
    with pytest.raises(HTTPException) as error:
        formar_numero(ReglaEntrada(prefijo="2200"), secuencia, "001")
    assert error.value.status_code == 409
    assert cast(dict[str, object], error.value.detail)["code"] == "SECUENCIA_AGOTADA"


def test_modulo_diez_vector_luhn_conocido():
    assert verificador("7992739871", "MODULO_10") == "3"


def test_modulo_once_pesos_y_casos_especiales():
    # Suma ponderada 174: resto 9, complemento 2.
    assert verificador("123456789", "MODULO_11") == "2"
    assert verificador("0", "MODULO_11") == "0"
    assert verificador("6", "MODULO_11") == "1"


def test_agencia_forma_parte_del_formato_sin_perder_ceros():
    regla = ReglaEntrada(prefijo="12", incluye_agencia=True, longitud_secuencia=6)
    assert formar_numero(regla, 1, "001") == "12001000001"
    with pytest.raises(HTTPException):
        formar_numero(regla, 1, "1")


@pytest.mark.parametrize(
    "datos",
    [
        {"prefijo": "AH"},
        {"prefijo": "١"},
        {"prefijo": "1234567"},
        {"prefijo": "22", "longitudSecuencia": True},
        {"prefijo": "22", "usada": False},
        {"prefijo": "22", "ultimoNumero": 1},
    ],
)
def test_cliente_no_inyecta_contador_ni_estado(datos):
    with pytest.raises(ValidationError):
        ReglaEntrada.model_validate(datos)


def test_prefijos_distintos_pueden_intersectar_un_mismo_numero():
    assert formatos_intersectan(
        ReglaEntrada(prefijo="22", longitud_secuencia=10),
        ReglaEntrada(prefijo="2200", longitud_secuencia=8),
    )
    assert not formatos_intersectan(
        ReglaEntrada(prefijo="33"), ReglaEntrada(prefijo="22")
    )

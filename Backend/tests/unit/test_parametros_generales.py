"""Tipos y banderas E0-09 sin sustituir las verificaciones SQL."""

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.parametros.tipos import convertir


@pytest.mark.parametrize(
    "tipo,entrada,esperado",
    [
        ("Entero", "12", 12),
        ("Decimal", "0.1250", Decimal("0.1250")),
        ("Booleano", "false", False),
        ("Booleano", "true", True),
        ("Hora", "23:59", "23:59"),
        ("Hora", "00:00", "00:00"),
        ("Texto", "nombre comercial", "nombre comercial"),
        ("Lista", '["A","B"]', ["A", "B"]),
        ("Lista", "[]", []),
    ],
)
def test_conversion_tipados(tipo, entrada, esperado):
    assert convertir({"TipoDato": tipo}, entrada) == esperado


@pytest.mark.parametrize(
    "tipo,entrada",
    [
        ("Entero", "1.0"),
        ("Entero", "01"),
        ("Entero", "true"),
        ("Entero", "1e2"),
        ("Decimal", "NaN"),
        ("Decimal", "Infinity"),
        ("Decimal", "0.12345"),
        ("Decimal", "1e2"),
        ("Booleano", "True"),
        ("Booleano", "1"),
        ("Hora", "24:00"),
        ("Hora", "12:60"),
        ("Lista", "{}"),
        ("Lista", "[1]"),
        ("Lista", "null"),
        ("Texto", "x" * 501),
    ],
)
def test_valores_invalidos(tipo, entrada):
    with pytest.raises(HTTPException, match="TIPO_PARAMETRO_INVALIDO"):
        convertir({"TipoDato": tipo}, entrada)


@pytest.mark.parametrize(
    "entrada,permitido", [("1", True), ("10", True), ("0", False), ("11", False)]
)
def test_limites_inclusivos(entrada, permitido):
    p = {"TipoDato": "Entero", "ValorMinimo": Decimal(1), "ValorMaximo": Decimal(10)}
    if permitido:
        assert convertir(p, entrada) == int(entrada)
    else:
        with pytest.raises(HTTPException, match="VALOR_FUERA_DE_RANGO"):
            convertir(p, entrada)


def test_opciones_tipadas_sin_redondeo_float():
    p = {"TipoDato": "Decimal", "ValoresPermitidos": "[0.1,0.3]"}
    assert convertir(p, "0.1") == Decimal("0.1")
    with pytest.raises(HTTPException, match="VALOR_NO_PERMITIDO"):
        convertir(p, "0.2")
    assert convertir(
        {"TipoDato": "Lista", "ValoresPermitidos": '["A","B"]'}, '["B"]'
    ) == ["B"]


@pytest.mark.parametrize(
    "tipo,valor,opciones",
    [
        ("Booleano", "true", "[1]"),
        ("Entero", "1", "[true]"),
        ("Decimal", "1", "[true]"),
    ],
)
def test_opciones_no_confunden_booleanos_y_numeros(tipo, valor, opciones):
    with pytest.raises(HTTPException, match="VALOR_NO_PERMITIDO"):
        convertir({"TipoDato": tipo, "ValoresPermitidos": opciones}, valor)

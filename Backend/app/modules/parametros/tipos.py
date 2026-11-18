"""Conversion estricta del contrato E0-09, sin leer configuracion ni bases."""

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.api.errors import problema


def convertir(definicion: dict[str, Any], valor: str) -> object:
    if not isinstance(valor, str) or len(valor) > 500:
        raise problema(
            422,
            "TIPO_PARAMETRO_INVALIDO",
            "Se requiere un valor de hasta 500 caracteres.",
        )
    tipo = definicion["TipoDato"]
    try:
        if tipo == "Entero":
            if not re.fullmatch(r"-?(0|[1-9][0-9]*)", valor):
                raise ValueError
            resultado: object = int(valor)
        elif tipo == "Decimal":
            if not re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]{1,4})?", valor):
                raise ValueError
            numero = Decimal(valor)
            if not numero.is_finite():
                raise ValueError
            resultado = numero
        elif tipo == "Booleano":
            if valor not in ("true", "false"):
                raise ValueError
            resultado = valor == "true"
        elif tipo == "Hora":
            if not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", valor):
                raise ValueError
            resultado = valor
        elif tipo == "Lista":
            lista = json.loads(valor)
            if not isinstance(lista, list) or not all(
                isinstance(x, str) for x in lista
            ):
                raise ValueError
            resultado = lista
        elif tipo == "Texto":
            resultado = valor
        else:
            raise ValueError
    except (ValueError, InvalidOperation, TypeError):
        raise problema(
            422, "TIPO_PARAMETRO_INVALIDO", "El valor no corresponde al tipo declarado."
        ) from None
    if tipo in ("Entero", "Decimal"):
        numero = Decimal(valor)
        minimo, maximo = definicion.get("ValorMinimo"), definicion.get("ValorMaximo")
        if (minimo is not None and numero < minimo) or (
            maximo is not None and numero > maximo
        ):
            raise problema(
                422, "VALOR_FUERA_DE_RANGO", "El valor esta fuera del rango permitido."
            )
    permitidos = definicion.get("ValoresPermitidos")
    if permitidos is not None:
        opciones = json.loads(permitidos, parse_float=Decimal)
        if tipo == "Booleano":
            opciones = [x for x in opciones if isinstance(x, bool)]
        elif tipo == "Entero":
            opciones = [
                x for x in opciones if isinstance(x, int) and not isinstance(x, bool)
            ]
        elif tipo == "Decimal":
            opciones = [
                x
                for x in opciones
                if isinstance(x, (int, Decimal)) and not isinstance(x, bool)
            ]
        admitido = (
            all(item in opciones for item in resultado)
            if tipo == "Lista" and isinstance(resultado, list)
            else resultado in opciones
        )
        if not admitido:
            raise problema(
                422,
                "VALOR_NO_PERMITIDO",
                "El valor no pertenece a las opciones permitidas.",
            )
    return resultado

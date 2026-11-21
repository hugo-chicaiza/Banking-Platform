"""Algoritmos puros de numeracion, compartidos por ejemplo y asignacion real."""

import re

from app.core.api.errors import problema
from app.modules.productos.numeracion_schemas import ReglaEntrada


def verificador(base: str, algoritmo: str) -> str:
    if algoritmo == "NINGUNO":
        return ""
    digitos = [int(v) for v in reversed(base)]
    if algoritmo == "MODULO_10":
        productos = [v * (2 if i % 2 == 0 else 1) for i, v in enumerate(digitos)]
        suma = sum(v // 10 + v % 10 for v in productos)
        return str((-suma) % 10)
    if algoritmo == "MODULO_11":
        # Complemento con pesos 2..7 desde la derecha; 11 -> 0 y 10 -> 1.
        complemento = 11 - sum(v * (2 + i % 6) for i, v in enumerate(digitos)) % 11
        return str(0 if complemento == 11 else 1 if complemento == 10 else complemento)
    raise problema(422, "ALGORITMO_INVALIDO", "El algoritmo verificador no es valido.")


def formar_numero(regla: ReglaEntrada, secuencia: int, agencia: str) -> str:
    if not 1 <= secuencia < 10**regla.longitud_secuencia:
        raise problema(
            409, "SECUENCIA_AGOTADA", "La secuencia de cuentas esta agotada."
        )
    if regla.incluye_agencia and not re.fullmatch(r"[0-9]{3}", agencia):
        raise problema(
            422, "AGENCIA_INVALIDA", "Se requiere una agencia de tres digitos."
        )
    base = (
        regla.prefijo
        + (agencia if regla.incluye_agencia else "")
        + str(secuencia).zfill(regla.longitud_secuencia)
    )
    return base + verificador(base, regla.algoritmo_verificador)


def formatos_comparten_serie(a: ReglaEntrada, b: ReglaEntrada) -> bool:
    return a == b


def formatos_intersectan(a: ReglaEntrada, b: ReglaEntrada) -> bool:
    def longitud(v: ReglaEntrada) -> int:
        return (
            len(v.prefijo)
            + (3 if v.incluye_agencia else 0)
            + v.longitud_secuencia
            + (v.algoritmo_verificador != "NINGUNO")
        )

    return longitud(a) == longitud(b) and (
        a.prefijo.startswith(b.prefijo) or b.prefijo.startswith(a.prefijo)
    )

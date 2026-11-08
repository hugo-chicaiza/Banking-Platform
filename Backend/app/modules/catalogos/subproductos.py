"""Tipo de tarjeta de un subproducto (CAT-07 y TAR-01).

La base no tiene una columna con el tipo: lo define el prefijo del código del
subproducto (F-07). Un subproducto de tarjeta nuevo debe seguir esta convención.
"""

from typing import Literal

TipoTarjeta = Literal["Debito", "Credito"]

PREFIJO_TIPO_TARJETA: dict[str, TipoTarjeta] = {"TDB": "Debito", "TCR": "Credito"}


def tipo_tarjeta_de(codigo_sub_producto: str) -> TipoTarjeta | None:
    """Debito (TDB…), Credito (TCR…) o None si el código no sigue la convención."""
    return PREFIJO_TIPO_TARJETA.get(codigo_sub_producto[:3].upper())

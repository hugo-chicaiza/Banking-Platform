"""Versión opaca de una asignación: datetime SQL persistido, sin datos de PIN."""

from datetime import datetime


class PinVersionNoDisponible(ValueError):
    """La versión no existe, es incoherente o no puede avanzar."""


def version_desde_fecha(fecha: object) -> str:
    if not isinstance(fecha, datetime) or fecha.tzinfo is not None or fecha.year < 1753:
        raise PinVersionNoDisponible("Versión de asignación no disponible")
    return fecha.isoformat(timespec="microseconds")


def validar_version(version: object) -> str:
    if not isinstance(version, str) or len(version) != 26:
        raise PinVersionNoDisponible("Versión de asignación no disponible")
    try:
        fecha = datetime.fromisoformat(version)
        if version_desde_fecha(fecha) != version:
            raise PinVersionNoDisponible("Versión de asignación no disponible")
    except (TypeError, ValueError):
        raise PinVersionNoDisponible("Versión de asignación no disponible") from None
    return version

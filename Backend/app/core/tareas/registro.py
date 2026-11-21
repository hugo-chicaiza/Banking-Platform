"""Registro de tareas programadas en código (E0-06). Cada código existe también en
`Sistema.Tarea` (descripción, programación, si admite ejecución manual y su ventana)."""

from app.core.tareas.ejecutor import Conteo, Tarea, TareaRechazada

# Las de aprobaciones tienen su propio ejecutor (E0-08) con el mismo bloqueo y registro
APROBACIONES = ("APR_RECUPERACION", "APR_RESUMEN_ANTIGUAS", "APR_AUD_RELEVO")


def _atm06_recuperacion() -> Conteo:
    """Recuperación de cambios de PIN ATM-06 pendientes (antes, solo un web job suelto)."""
    from app.modules.atm.cambio_pin_worker import ejecutar_configurado

    if ejecutar_configurado() != 0:
        raise TareaRechazada("ATM06_RECUPERACION terminó con error")
    return Conteo(procesados=1)


def _vigilante() -> Conteo:
    from app.core.tareas.vigilante import vigilar

    return vigilar()


TAREAS: dict[str, Tarea] = {
    "ATM06_RECUPERACION": Tarea("ATM06_RECUPERACION", _atm06_recuperacion),
    "SIS_VIGILANTE": Tarea("SIS_VIGILANTE", _vigilante),
}


def codigos() -> list[str]:
    return sorted([*TAREAS, *APROBACIONES])

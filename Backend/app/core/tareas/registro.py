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


def _liberar_retenciones() -> Conteo:
    from app.modules.cuentas.retenciones_tarea import liberar_vencidas

    return liberar_vencidas()


def _inactividad_cuentas() -> Conteo:
    from app.modules.cuentas.inactividad import ejecutar

    return ejecutar()


def _verificar_integridad() -> Conteo:
    from app.modules.auditoria.integridad import tarea_verificar

    return tarea_verificar()


def _archivar_bitacora() -> Conteo:
    from app.modules.auditoria.integridad import tarea_archivar

    return tarea_archivar()


def _vencer_tarjetas() -> Conteo:
    from app.modules.tarjetas.tareas import vencer

    return vencer()


def _anular_tarjetas_no_retiradas() -> Conteo:
    from app.modules.tarjetas.tareas import anular_no_retiradas

    return anular_no_retiradas()


TAREAS: dict[str, Tarea] = {
    "ATM06_RECUPERACION": Tarea("ATM06_RECUPERACION", _atm06_recuperacion),
    "SIS_VIGILANTE": Tarea("SIS_VIGILANTE", _vigilante),
    "CTA_LIBERAR_RETENCIONES": Tarea("CTA_LIBERAR_RETENCIONES", _liberar_retenciones),
    "CTA_INACTIVIDAD": Tarea("CTA_INACTIVIDAD", _inactividad_cuentas),
    "AUD_VERIFICAR_INTEGRIDAD": Tarea(
        "AUD_VERIFICAR_INTEGRIDAD", _verificar_integridad
    ),
    "AUD_ARCHIVAR": Tarea("AUD_ARCHIVAR", _archivar_bitacora),
    "TAR_VENCER": Tarea("TAR_VENCER", _vencer_tarjetas),
    "TAR_ANULAR_NO_RETIRADAS": Tarea(
        "TAR_ANULAR_NO_RETIRADAS", _anular_tarjetas_no_retiradas
    ),
}


def codigos() -> list[str]:
    return sorted([*TAREAS, *APROBACIONES])

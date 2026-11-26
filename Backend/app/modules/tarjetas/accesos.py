"""Asignaciones de Tarjetas y compatibilidad con el frontend desplegado."""

from collections.abc import Collection

from app.modules.seguridad.funciones_catalogo import (
    APROBAR_DESBLOQUEO_TARJETA,
    APROBAR_SOLICITUD_TARJETA,
    POR_ID,
)

_INDICADORES = {
    "tar-consultar": "tarjetas.consultar",
    "tar-consultar:historial": "tarjetas.verHistorial",
    "tar-solicitar": "tarjetas.emitir",
    "tar-solicitar:aprobar": APROBAR_SOLICITUD_TARJETA,
    "tar-estado": "tarjetas.cambiarEstado",
    "tar-estado:aprobar": APROBAR_DESBLOQUEO_TARJETA,
    "tar-pin": "tarjetas.asignarPin",
    "tar-pin:entregar": "tarjetas.verSobrePin",
}


def funciones_de_estado(roles: Collection[str]) -> frozenset[str]:
    return frozenset(
        funcion
        for funcion in (APROBAR_SOLICITUD_TARJETA, APROBAR_DESBLOQUEO_TARJETA)
        if set(roles).intersection(POR_ID[funcion].roles_iniciales)
    )


def permisos_para_frontend(
    permisos: Collection[str], roles: Collection[str], funciones: Collection[str] | None
) -> list[str]:
    """Conserva el contrato de /auth/me con señales de UI calculadas en el core."""
    efectivos = (
        set(funciones)
        if funciones is not None
        else {
            funcion
            for funcion in _INDICADORES.values()
            if set(roles).intersection(POR_ID[funcion].roles_iniciales)
        }
    )
    return [permiso for permiso in permisos if permiso not in _INDICADORES] + [
        indicador for indicador, funcion in _INDICADORES.items() if funcion in efectivos
    ]

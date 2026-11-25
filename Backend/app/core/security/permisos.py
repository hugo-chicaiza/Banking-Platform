"""Permisos de WorkOS que usa la API y su asignación a roles.

Regla: el rol decide qué se ve y, mientras no exista un permiso general para una
escritura, también quién la hace (require_roles). Solo las escrituras que tienen un
permiso en WorkOS lo exigen (require_permiso): productos (prd-) y contabilidad (con-).
Los permisos son generales, no uno por módulo ni por rol; uno nuevo se acuerda antes de
crearlo en WorkOS y agregarlo aquí.

La asignación de abajo es la que deben tener los roles en WorkOS; las pruebas la usan
para armar la sesión de cada rol. Cambiar este archivo no modifica el tenant. Slugs en
minúsculas: WorkOS no acepta mayúsculas.
"""

_TODOS = (
    "ADMIN",
    "SUPERVISOR",
    "ASESOR",
    "CAJERO",
    "CONTADOR",
    "AUDITOR",
    "APROBADOR_CREDITO",
)

PERMISOS: dict[str, tuple[str, ...]] = {
    # E0-08: permisos de aprobacion acordados; nunca se conceden por ser ADMIN.
    "parametros:aprobar": ("SUPERVISOR",),
    "agencias:aprobar": ("SUPERVISOR",),
    "cuentas:aprobar": ("SUPERVISOR",),
    "prd-consultar": tuple(r for r in _TODOS if r != "CAJERO"),
    "prd-editar": ("ADMIN",),
    "prd-condicion": ("ADMIN",),
    "prd-numeracion": ("ADMIN",),
    "prd-estado": ("ADMIN",),
    "productos:aprobar": ("SUPERVISOR",),
    "prd-exportar": _TODOS,
    "con-plantilla-editar": ("CONTADOR",),
    "con-plantilla-aprobar": ("CONTADOR",),
    "con-cuenta-editar": ("CONTADOR",),
    "con-reclasificacion-preparar": ("CONTADOR",),
    "con-reclasificacion-aprobar": ("CONTADOR",),
}


def permisos_de(roles: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Permisos que la asignación da a estos roles."""
    return tuple(p for p, con in PERMISOS.items() if set(con) & set(roles))

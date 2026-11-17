"""Permisos de escritura (WorkOS) y su asignación inicial a roles.

Regla: el rol decide qué se ve (pestañas y consultas, require_roles); el permiso decide
qué se cambia (crear, editar, activar o desactivar, eliminar, operar: require_permiso).
WorkOS asigna los permisos a roles; aquí está la asignación inicial, que repite quién
podía escribir antes de los permisos y las ampliaciones autorizadas. Las pruebas la
usan para armar la sesión de cada rol; la asignación real se configura en WorkOS.
Cambiar este archivo no modifica el tenant. Slugs en minúsculas: WorkOS no
acepta mayúsculas.
"""

PERMISOS: dict[str, tuple[str, ...]] = {
    "organizacion:editar": ("ADMIN",),
    "agencias:editar": ("ADMIN",),
    "usuarios:editar": ("ADMIN",),
    "productos:editar": ("ADMIN",),
    "productos:exportar": ("ADMIN", "SUPERVISOR", "ASESOR"),
    "catalogos:editar": ("ADMIN",),
    "clientes:editar": ("ASESOR", "ADMIN"),
    "clientes:estado": ("ASESOR", "SUPERVISOR", "ADMIN"),
    "clientes:riesgo": ("ASESOR", "SUPERVISOR", "ADMIN"),
    "cuentas:abrir": ("ASESOR", "ADMIN"),
    "cuentas:estado": ("ASESOR", "SUPERVISOR", "ADMIN"),
    "cuentas:cupos": ("SUPERVISOR", "ADMIN"),
    "tarjetas:emitir": ("ASESOR", "ADMIN"),
    "tarjetas:estado": ("ASESOR", "SUPERVISOR", "ADMIN"),
    "con-plantilla-editar": ("CONTADOR",),
    "contabilidad:editar": ("CONTADOR",),
    "con-cuenta-editar": ("CONTADOR",),
    "caja:operar": ("CAJERO",),
    "caja:autorizar": ("SUPERVISOR",),
    "boveda:operar": ("SUPERVISOR", "ADMIN"),
    "boveda:arqueo": ("SUPERVISOR", "AUDITOR", "ADMIN"),
}


def permisos_de(roles: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Permisos que la asignación inicial da a estos roles."""
    return tuple(p for p, con in PERMISOS.items() if set(con) & set(roles))

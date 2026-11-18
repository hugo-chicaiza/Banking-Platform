"""Contratos de Seguridad: permisos de los roles (WorkOS) y pestañas por rol."""

from typing import Annotated

from pydantic import Field, StringConstraints

from app.core.api.schemas import CamelModel
from app.core.security.auth import Rol

# Slugs de permiso de WorkOS: minúsculas, dígitos y _ . : -
SlugPermiso = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,63}$")]
# Ruta de una pestaña del menú (la clave es la URL del frontend, p. ej. /cuentas/abrir)
RutaPestana = Annotated[str, StringConstraints(pattern=r"^/[a-z0-9][a-z0-9/-]{0,78}$")]


class PermisoVista(CamelModel):
    slug: str
    nombre: str
    descripcion: str | None
    # Permisos de WorkOS (widgets:*): se listan pero no se asignan desde aquí
    sistema: bool


class PermisoCreate(CamelModel):
    # Permisos generales: prefijo del área y acción, p. ej. prd-aprobar o con-cerrar
    slug: Annotated[
        str, StringConstraints(pattern=r"^[a-z][a-z0-9]{1,9}-[a-z0-9][a-z0-9-]{1,40}$")
    ]
    nombre: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    descripcion: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None
    ) = None


class PermisoUpdate(CamelModel):
    nombre: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
        ]
        | None
    ) = None
    descripcion: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None
    ) = None


class RolVista(CamelModel):
    rol: Rol
    slug: str
    nombre: str
    descripcion: str | None
    permisos: list[str]


class PermisoAsignar(CamelModel):
    permiso: SlugPermiso


class PermisosRol(CamelModel):
    permisos: Annotated[list[SlugPermiso], Field(max_length=100)]


class PestanaRoles(CamelModel):
    pestana: RutaPestana
    roles: Annotated[list[Rol], Field(max_length=7)]


class PestanasConfig(CamelModel):
    """Configuración completa: reemplaza la anterior. Lista vacía = menú por defecto."""

    pestanas: Annotated[list[PestanaRoles], Field(max_length=100)]

"""HTTP de Seguridad: permisos de los roles (WorkOS) y pestañas del menú por rol.

Todo lo administra el rol ADMIN. GET /seguridad/pestanas lo lee cualquier usuario con
sesión: el menú de cada uno lo necesita.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, solo_parametros
from app.core.api.middleware import ip_cliente
from app.core.database.db import seguridad
from app.core.security.auth import (
    Rol,
    Usuario,
    UsuarioAuditoria,
    require_auth,
    require_roles,
)
from app.modules.seguridad import service
from app.modules.seguridad.schemas import (
    PermisoAsignar,
    PermisoCreate,
    PermisosRol,
    PermisoUpdate,
    PermisoVista,
    PestanaRoles,
    PestanasConfig,
    RolVista,
)

router = APIRouter(
    prefix="/seguridad",
    tags=["seguridad"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth), Depends(solo_parametros())],
)
Admin = Annotated[Usuario, Depends(require_roles("ADMIN"))]
Db = Annotated[Connection, Depends(seguridad)]
SlugPath = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,63}$")]
_ADMIN = {"x-roles": ["ADMIN"]}


@router.get(
    "/permisos",
    response_model=list[PermisoVista],
    operation_id="SEG01",
    openapi_extra=_ADMIN,
)
def listar_permisos(_: Admin) -> list[PermisoVista]:
    """Catálogo de permisos de WorkOS (los de sistema van marcados y al final)."""
    return service.listar_permisos()


@router.post(
    "/permisos",
    response_model=PermisoVista,
    status_code=201,
    operation_id="SEG09",
    openapi_extra=_ADMIN,
)
def crear_permiso(request: Request, datos: PermisoCreate, admin: Admin) -> PermisoVista:
    """Crea un permiso general en WorkOS (sin asignarlo a ningún rol)."""
    return service.crear_permiso(datos, admin, ip_cliente(request.scope))


@router.delete(
    "/permisos/{slug}", status_code=204, operation_id="SEG10", openapi_extra=_ADMIN
)
def borrar_permiso(request: Request, slug: SlugPath, admin: Admin) -> Response:
    """Borra el permiso y lo quita de los roles. No borra los que exige la aplicación."""
    service.borrar_permiso(slug, admin, ip_cliente(request.scope))
    return Response(status_code=204)


@router.patch(
    "/permisos/{slug}",
    response_model=PermisoVista,
    operation_id="SEG02",
    openapi_extra=_ADMIN,
)
def editar_permiso(
    request: Request, slug: SlugPath, cambios: PermisoUpdate, admin: Admin
) -> PermisoVista:
    """Cambia nombre o descripción. El slug no cambia (WorkOS no lo permite)."""
    return service.editar_permiso(slug, cambios, admin, ip_cliente(request.scope))


@router.get(
    "/roles", response_model=list[RolVista], operation_id="SEG03", openapi_extra=_ADMIN
)
def listar_roles(_: Admin) -> list[RolVista]:
    """Los 7 roles del sistema con sus permisos en WorkOS."""
    return service.listar_roles()


@router.post(
    "/roles/{rol}/permisos",
    response_model=RolVista,
    operation_id="SEG04",
    openapi_extra=_ADMIN,
)
def agregar_permiso(
    request: Request, rol: Rol, datos: PermisoAsignar, admin: Admin
) -> RolVista:
    """Asigna un permiso al rol. Aplica en la siguiente sesión de cada usuario."""
    return service.agregar_permiso(rol, datos.permiso, admin, ip_cliente(request.scope))


@router.delete(
    "/roles/{rol}/permisos/{permiso}",
    response_model=RolVista,
    operation_id="SEG05",
    openapi_extra=_ADMIN,
)
def quitar_permiso(
    request: Request, rol: Rol, permiso: SlugPath, admin: Admin
) -> RolVista:
    """Quita un permiso del rol."""
    return service.quitar_permiso(rol, permiso, admin, ip_cliente(request.scope))


@router.put(
    "/roles/{rol}/permisos",
    response_model=RolVista,
    operation_id="SEG06",
    openapi_extra=_ADMIN,
)
def reemplazar_permisos(
    request: Request, rol: Rol, datos: PermisosRol, admin: Admin
) -> RolVista:
    """Deja al rol exactamente con estos permisos (los de sistema se conservan)."""
    return service.reemplazar_permisos(
        rol, datos.permisos, admin, ip_cliente(request.scope)
    )


@router.get("/pestanas", response_model=list[PestanaRoles], operation_id="SEG07")
def listar_pestanas(conn: Db) -> list[PestanaRoles]:
    """Pestañas con roles personalizados; las que no aparecen usan el menú por defecto."""
    return service.listar_pestanas(conn)


@router.put(
    "/pestanas",
    response_model=list[PestanaRoles],
    operation_id="SEG08",
    openapi_extra=_ADMIN,
)
def guardar_pestanas(
    request: Request,
    config: PestanasConfig,
    admin: Admin,
    id_admin: UsuarioAuditoria,
    conn: Db,
) -> list[PestanaRoles]:
    """Reemplaza la configuración completa. Solo cambia el menú: cada API sigue
    validando rol o permiso."""
    return service.guardar_pestanas(
        conn, config, admin, id_admin, ip_cliente(request.scope)
    )

"""Seguridad: permisos de los roles del sistema en WorkOS y pestañas visibles por rol.

- Permisos: un ADMIN los crea, edita (nombre y descripción) y borra. Un permiso nuevo
  no habilita nada hasta que el código lo exija (core/security/permisos.py); por eso no
  se borra uno que el código usa. Los de sistema (widgets:*) no se tocan.
- Roles: solo los 7 roles del sistema (org-*). Un cambio de permisos aplica a la
  siguiente sesión (o refresco) de cada usuario, cuando WorkOS emite el token nuevo.
- Pestañas: solo deciden qué muestra el menú; cada API sigue validando rol o permiso.
"""

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.security.auth import ROLES, Rol, Usuario, slug_rol
from app.core.security.operador import auditar
from app.core.security.permisos import PERMISOS
from app.integrations.workos_client import get_organizacion_id, get_workos
from app.modules.auth.service import _workos  # traducción común de errores de WorkOS
from app.modules.seguridad import repository
from app.modules.seguridad.schemas import (
    PermisoCreate,
    PermisoUpdate,
    PermisoVista,
    PestanaRoles,
    PestanasConfig,
    RolVista,
)

_TABLA_PERMISOS = "WorkOS.Permisos"
_TABLA_ROLES = "WorkOS.Roles"
_TABLA_PESTANAS = "Seguridad.PestanaRol"
# Las pestañas de Seguridad no se configuran: así un ADMIN no puede quitarse el acceso
PESTANAS_FIJAS = frozenset({"/", "/seguridad/roles", "/seguridad/pestanas"})


def _permisos() -> list[PermisoVista]:
    autorizacion = get_workos().authorization
    vistos: list[PermisoVista] = []
    after: str | None = None
    with _workos("list_permissions"):
        while True:
            pagina = autorizacion.list_permissions(limit=100, after=after, order="asc")
            vistos += [
                PermisoVista(
                    slug=p.slug,
                    nombre=p.name,
                    descripcion=p.description,
                    sistema=p.system,
                )
                for p in pagina.data
            ]
            after = pagina.list_metadata.after
            if not after:
                break
    return sorted(vistos, key=lambda p: (p.sistema, p.slug))


def listar_permisos() -> list[PermisoVista]:
    return _permisos()


def _asignable(slug: str, catalogo: list[PermisoVista] | None = None) -> PermisoVista:
    permiso = next((p for p in catalogo or _permisos() if p.slug == slug), None)
    if permiso is None:
        raise problema(404, "PERMISO_NO_ENCONTRADO", "El permiso no existe en WorkOS.")
    if permiso.sistema:
        raise problema(
            409,
            "PERMISO_DE_SISTEMA",
            "Los permisos de sistema de WorkOS no se administran aquí.",
        )
    return permiso


def crear_permiso(datos: PermisoCreate, usuario: Usuario, ip: str) -> PermisoVista:
    with auditar(
        "CREAR_PERMISO",
        _TABLA_PERMISOS,
        usuario,
        ip,
        f"permiso={datos.slug}",
        datos.slug,
    ):
        if any(p.slug == datos.slug for p in _permisos()):
            raise problema(
                409, "PERMISO_DUPLICADO", "Ya existe un permiso con ese código."
            )
        with _workos("create_permission"):
            p = get_workos().authorization.create_permission(
                slug=datos.slug, name=datos.nombre, description=datos.descripcion
            )
        return PermisoVista(
            slug=p.slug, nombre=p.name, descripcion=p.description, sistema=p.system
        )


def borrar_permiso(slug: str, usuario: Usuario, ip: str) -> None:
    """WorkOS lo quita también de los roles que lo tenían."""
    with auditar(
        "BORRAR_PERMISO", _TABLA_PERMISOS, usuario, ip, f"permiso={slug}", slug
    ):
        _asignable(slug)
        if slug in PERMISOS:
            raise problema(
                409,
                "PERMISO_EN_USO",
                "La aplicación exige este permiso; borrarlo dejaría sin acceso a quienes lo tienen.",
            )
        with _workos("delete_permission"):
            get_workos().authorization.delete_permission(slug)


def editar_permiso(
    slug: str, cambios: PermisoUpdate, usuario: Usuario, ip: str
) -> PermisoVista:
    if cambios.nombre is None and cambios.descripcion is None:
        raise problema(422, "SIN_CAMBIOS", "Envíe nombre o descripción.")
    with auditar(
        "EDITAR_PERMISO", _TABLA_PERMISOS, usuario, ip, f"permiso={slug}", slug
    ):
        _asignable(slug)
        with _workos("update_permission"):
            p = get_workos().authorization.update_permission(
                slug, name=cambios.nombre, description=cambios.descripcion
            )
        return PermisoVista(
            slug=p.slug, nombre=p.name, descripcion=p.description, sistema=p.system
        )


def _rol_de_slug(slug: str) -> Rol | None:
    return next((r for r in ROLES if slug_rol(r) == slug), None)


def listar_roles() -> list[RolVista]:
    with _workos("list_organization_roles"):
        roles = get_workos().authorization.list_organization_roles(
            get_organizacion_id()
        )
    vistas = []
    for r in roles.data:
        rol = _rol_de_slug(r.slug)
        if rol is not None:
            vistas.append(
                RolVista(
                    rol=rol,
                    slug=r.slug,
                    nombre=r.name,
                    descripcion=r.description,
                    permisos=sorted(r.permissions),
                )
            )
    return sorted(vistas, key=lambda v: ROLES.index(v.rol))


def _rol(rol: Rol) -> RolVista:
    vista = next((v for v in listar_roles() if v.rol == rol), None)
    if vista is None:
        raise problema(404, "ROL_NO_ENCONTRADO", "El rol no existe en WorkOS.")
    return vista


def agregar_permiso(rol: Rol, permiso: str, usuario: Usuario, ip: str) -> RolVista:
    with auditar(
        "ASIGNAR_PERMISO_ROL",
        _TABLA_ROLES,
        usuario,
        ip,
        f"rol={rol} permiso={permiso}",
        rol,
    ):
        _asignable(permiso)
        if permiso not in _rol(rol).permisos:
            with _workos("add_organization_role_permission"):
                get_workos().authorization.add_organization_role_permission(
                    organization_id=get_organizacion_id(),
                    slug=slug_rol(rol),
                    permission_slug=permiso,
                )
        return _rol(rol)


def quitar_permiso(rol: Rol, permiso: str, usuario: Usuario, ip: str) -> RolVista:
    with auditar(
        "QUITAR_PERMISO_ROL",
        _TABLA_ROLES,
        usuario,
        ip,
        f"rol={rol} permiso={permiso}",
        rol,
    ):
        if permiso not in _rol(rol).permisos:
            raise problema(404, "PERMISO_NO_ASIGNADO", "El rol no tiene ese permiso.")
        with _workos("remove_organization_role_permission"):
            get_workos().authorization.remove_organization_role_permission(
                organization_id=get_organizacion_id(),
                slug=slug_rol(rol),
                permission_slug=permiso,
            )
        return _rol(rol)


def reemplazar_permisos(
    rol: Rol, permisos: list[str], usuario: Usuario, ip: str
) -> RolVista:
    nuevos = sorted(set(permisos))
    with auditar(
        "REEMPLAZAR_PERMISOS_ROL",
        _TABLA_ROLES,
        usuario,
        ip,
        f"rol={rol} permisos={','.join(nuevos)}",
        rol,
    ):
        catalogo = _permisos()
        for p in nuevos:
            _asignable(p, catalogo)
        # Los permisos de sistema que ya tenga el rol se conservan: no se administran aquí
        de_sistema = {p.slug for p in catalogo if p.sistema}
        conservar = [p for p in _rol(rol).permisos if p in de_sistema]
        with _workos("set_organization_role_permissions"):
            get_workos().authorization.set_organization_role_permissions(
                organization_id=get_organizacion_id(),
                slug=slug_rol(rol),
                permissions=sorted({*nuevos, *conservar}),
            )
        return _rol(rol)


def listar_pestanas(conn: Connection) -> list[PestanaRoles]:
    vistas = []
    for pestana, roles in repository.pestanas(conn):
        validos: list[Rol] = [r for r in ROLES if r in roles.split(",")]
        if pestana not in PESTANAS_FIJAS:
            vistas.append(PestanaRoles(pestana=pestana, roles=validos))
    return vistas


def guardar_pestanas(
    conn: Connection, config: PestanasConfig, usuario: Usuario, id_usuario: int, ip: str
) -> list[PestanaRoles]:
    from app.modules.seguridad import funciones

    if funciones.activa():
        raise problema(
            409,
            "EDITOR_ANTERIOR_SOLO_LECTURA",
            "El modelo de funciones está activo. Utiliza su editor para guardar accesos.",
        )
    rutas = [p.pestana for p in config.pestanas]
    if len(rutas) != len(set(rutas)):
        raise problema(
            422, "PESTANA_DUPLICADA", "Cada pestaña se configura una sola vez."
        )
    fijas = sorted(set(rutas) & PESTANAS_FIJAS)
    if fijas:
        raise problema(
            422, "PESTANA_NO_CONFIGURABLE", f"No se configura: {', '.join(fijas)}."
        )
    from app.modules.seguridad import accesos

    if accesos.activa() or config.version is not None:
        return accesos.guardar(conn, config, usuario, id_usuario, ip)
    filas = [
        (p.pestana, ",".join(r for r in ROLES if r in p.roles)) for p in config.pestanas
    ]
    with auditar(
        "CONFIGURAR_PESTANAS",
        _TABLA_PESTANAS,
        usuario,
        ip,
        f"pestanas={len(filas)}",
    ):
        with conn.begin():
            repository.reemplazar_pestanas(conn, filas, id_usuario)
        return listar_pestanas(conn)

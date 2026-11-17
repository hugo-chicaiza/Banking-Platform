"""Sesión simulada para pruebas: reemplaza solo la validación de la cookie de WorkOS.

Las rutas siguen aplicando require_roles y require_permiso. usuario_con_roles da los
permisos que la asignación inicial (permisos.py) da a esos roles, como WorkOS, así que
una prueba de 403 solo necesita pasar un usuario con otros roles.
"""

from dataclasses import replace

from fastapi import FastAPI

from app.core.security.auth import (
    ROLES,
    Usuario,
    id_usuario_auditoria,
    usuario_actual,
)
from app.core.security.permisos import PERMISOS, permisos_de

ID_AUDITORIA = 1

USUARIO = Usuario(
    id_usuario="user_prueba",
    id_sesion="session_prueba",
    id_organizacion=None,
    nombre="Usuario de prueba",
    email="prueba@example.com",
    roles=ROLES,
    permisos=tuple(PERMISOS),
    id_agencia="001",
    # Registrado (KeyUsuario): require_auth deja pasar
    id_interno=ID_AUDITORIA,
)


def usuario_con_roles(*roles: str) -> Usuario:
    return replace(USUARIO, roles=roles, permisos=permisos_de(roles))


def simular_sesion(app: FastAPI, usuario: Usuario = USUARIO) -> None:
    app.dependency_overrides[usuario_actual] = lambda: usuario
    app.dependency_overrides[id_usuario_auditoria] = lambda: ID_AUDITORIA

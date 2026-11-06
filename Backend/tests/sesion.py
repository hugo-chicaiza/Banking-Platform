"""Sesión simulada para pruebas: reemplaza solo la validación de la cookie de WorkOS.

Las rutas siguen aplicando require_roles con los roles de este usuario, así que una
prueba de 403 solo necesita pasar un usuario con otros roles.
"""

from dataclasses import replace

from fastapi import FastAPI

from app.core.security.auth import (
    ROLES,
    Usuario,
    id_usuario_auditoria,
    usuario_actual,
    usuario_de_sesion,
)

ID_AUDITORIA = 1

USUARIO = Usuario(
    id_usuario="user_prueba",
    id_sesion="session_prueba",
    id_organizacion=None,
    nombre="Usuario de prueba",
    email="prueba@example.com",
    roles=ROLES,
    permisos=(),
    id_agencia="001",
)


def usuario_con_roles(*roles: str) -> Usuario:
    return replace(USUARIO, roles=roles)


def simular_sesion(app: FastAPI, usuario: Usuario = USUARIO) -> None:
    app.dependency_overrides[usuario_actual] = lambda: usuario
    # /auth/me usa la sesión real de WorkOS, no la de las APIs
    app.dependency_overrides[usuario_de_sesion] = lambda: usuario
    app.dependency_overrides[id_usuario_auditoria] = lambda: ID_AUDITORIA

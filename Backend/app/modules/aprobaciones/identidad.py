"""Revalidacion WorkOS sin cache entre aprobaciones ni privilegios implicitos ADMIN."""

from dataclasses import dataclass

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from workos.exceptions import BaseRequestException, NotFoundException

from app.core.api.errors import problema
from app.core.security.auth import normalizar_roles
from app.integrations.workos_client import get_organizacion_id, get_workos
from app.modules.aprobaciones.motores import motor
from app.modules.auth.agencias_repository import asignaciones


@dataclass(frozen=True)
class Actor:
    sujeto: str
    organizacion: str
    nombre: str | None
    id_interno: int
    roles: tuple[str, ...]
    permisos: frozenset[str]
    agencias: tuple[str, ...]

    @property
    def global_admin(self) -> bool:
        return "ADMIN" in self.roles and not bool(
            {"CAJERO", "ASESOR"} & set(self.roles)
        )

    def alcance(self, agencia: str | None) -> None:
        if (
            agencia is not None
            and not self.global_admin
            and agencia not in self.agencias
        ):
            raise problema(
                404, "SOLICITUD_NO_ENCONTRADA", "La solicitud no esta disponible."
            )


def vigente(sujeto: str, organizacion: str) -> Actor:
    try:
        if organizacion != get_organizacion_id():
            raise problema(
                403, "ORGANIZACION_NO_AUTORIZADA", "La organizacion no esta autorizada."
            )
        cliente = get_workos()
        membresias = list(
            cliente.user_management.list_organization_memberships(
                user_id=sujeto, organization_id=organizacion, statuses=["active"]
            )
        )
        if len(membresias) != 1:
            raise problema(
                403,
                "ACTOR_NO_ACTIVO",
                "El usuario no tiene una membresia activa unica.",
            )
        miembro = membresias[0]
        slugs = sorted({r["slug"] for r in (miembro.roles or [miembro.role])})
        roles = normalizar_roles(slugs, None)
        permisos: set[str] = set()
        for slug in slugs:
            permisos.update(
                cliente.authorization.get_organization_role(
                    organizacion, slug
                ).permissions
            )
        with motor("seguridad").connect() as conn:
            filas = (
                conn.execute(
                    text("""SELECT TOP(2) UsuarioID,Estado,Nombres,Apellidos
                FROM Organizacion.Usuarios WHERE KeyUsuario COLLATE Latin1_General_100_BIN2=:sujeto"""),
                    {"sujeto": sujeto},
                )
                .mappings()
                .all()
            )
            if len(filas) != 1 or filas[0]["Estado"] != "Activo":
                raise problema(
                    403,
                    "ACTOR_NO_ACTIVO",
                    "El vinculo institucional no esta activo o no es unico.",
                )
            fila = filas[0]
            agencias = tuple(asignaciones(conn, fila["UsuarioID"]))
        nombre = (
            " ".join(
                str(fila[k] or "").strip() for k in ("Nombres", "Apellidos")
            ).strip()
            or None
        )
        return Actor(
            sujeto,
            organizacion,
            nombre,
            int(fila["UsuarioID"]),
            roles,
            frozenset(permisos),
            agencias,
        )
    except NotFoundException:
        raise problema(
            403, "ACTOR_NO_ACTIVO", "La identidad ya no esta activa."
        ) from None
    except (BaseRequestException, httpx.HTTPError, SQLAlchemyError, RuntimeError):
        raise problema(
            503,
            "IDENTIDAD_NO_DISPONIBLE",
            "No se pudo verificar la identidad y sus permisos actuales.",
        ) from None

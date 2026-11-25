"""Cambio de roles con decisión persistida y reconciliación sobre la misma solicitud."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.core.security.auth import codigo_agencia, normalizar_roles, slug_rol
from app.integrations.workos_client import get_organizacion_id, get_workos
from app.modules.aprobaciones import identidad
from app.modules.aprobaciones.congelacion import congelar
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.auth import (
    agencias,
    agencias_repository,
    politica_roles,
    repository,
    service,
)
from app.modules.auth.schemas import RolUpdate
from app.modules.caja.repository import jornada_abierta_de_usuario

CODIGO = "SEG-USUARIO-ROLES"
TIPO = "UsuarioRoles"


@contextmanager
def corte_protegido() -> Iterator[None]:
    if not get_settings().e104_corte_asignacion_caja:
        yield
        return
    with get_engine("cooperativa").connect() as coop:
        service.bloquear_corte_caja(coop)
        yield


def validar_aprobador(objetivo: Objetivo, id_aprobador: int) -> None:
    if int(objetivo.id) == id_aprobador:
        raise problema(
            403, "AUTOGESTION_NO_PERMITIDA", "No puede aprobar sus propios roles."
        )


class CambioRoles:
    def _fila(self, conn: Connection, objetivo: Objetivo) -> repository.Fila:
        service._serializar_cambios_administrativos(conn)
        fila = service._cargar(conn, int(objetivo.id), bloquear=True)
        if get_settings().e104_recuperar_correo and repository.sincronizacion_pendiente(
            conn, int(objetivo.id)
        ):
            raise problema(
                409,
                "USUARIO_EN_CONCILIACION",
                "El usuario tiene una sincronización pendiente.",
            )
        if fila["Estado"] != "Activo" or not fila["KeyUsuario"]:
            raise problema(
                409,
                "USUARIO_NO_HABILITADO",
                "El usuario debe estar activo y vinculado.",
            )
        return fila

    def _version(self, fila: repository.Fila) -> str:
        return congelar(
            {
                "vinculo": fila["KeyUsuario"],
                "agencia": fila["AgenciaID"],
                "estado": fila["Estado"],
            }
        ).huella.hex()

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        return self._version(self._fila(conn, objetivo))

    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan:
        fila = self._fila(conn, objetivo)
        datos = RolUpdate.model_validate(contenido)
        nuevos = normalizar_roles(datos.roles, datos.rol)
        membresia = service._membresia(fila["KeyUsuario"])
        anteriores = service._roles(fila)
        if (
            membresia is None
            or membresia.status != "active"
            or service._slugs(membresia) != {slug_rol(rol) for rol in anteriores}
        ):
            raise problema(
                409, "ROLES_DESINCRONIZADOS", "La membresía no coincide con SQL."
            )
        if (
            "CAJERO" in anteriores
            and "CAJERO" not in nuevos
            and not get_settings().e104_corte_asignacion_caja
        ):
            raise problema(
                409,
                "CORTE_CAJA_PENDIENTE",
                "El cambio requiere el corte de asignaciones de Caja.",
            )
        antes = {"roles": list(anteriores)}
        despues = {"roles": list(nuevos)}
        return Plan(
            {"anteriores": antes["roles"], "roles": despues["roles"]},
            antes,
            despues,
            self._version(fila),
        )

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict[str, Any],
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        if not get_settings().e104_politica_roles_activa:
            raise problema(
                503,
                "OPERACION_NO_CONFIGURADA",
                "La aprobación institucional de roles está suspendida.",
            )
        fila = self._fila(conn, objetivo)
        id_usuario = int(objetivo.id)
        actor = identidad.vigente(solicitante, get_organizacion_id())
        if not actor.global_admin or actor.id_interno == id_usuario:
            raise problema(
                403, "SIN_PERMISO", "El solicitante carece de autorización vigente."
            )
        anteriores = tuple(contenido["anteriores"])
        nuevos = normalizar_roles(contenido["roles"], None)
        if (
            "CAJERO" in anteriores
            and "CAJERO" not in nuevos
            and not get_settings().e104_corte_asignacion_caja
        ):
            raise problema(
                409,
                "CORTE_CAJA_PENDIENTE",
                "El cambio requiere el corte de asignaciones de Caja.",
            )
        if not politica_roles.vigente().requiere_aprobacion(
            actor.roles, anteriores, nuevos
        ):
            raise problema(409, "POLITICA_ROLES_CAMBIO", "La política de roles cambió.")
        agencias.validar_matriz(
            nuevos,
            agencias_repository.asignaciones(conn, id_usuario),
            codigo_agencia(fila["AgenciaID"]),
        )
        with get_engine("cooperativa").connect() as coop:
            if jornada_abierta_de_usuario(coop, id_usuario, bloquear=False):
                raise problema(
                    409, "CAJERO_CON_JORNADA_ABIERTA", "Cierre primero la jornada."
                )
        if "ADMIN" not in nuevos:
            service._validar_ultimo_admin(conn, fila)
        antes = {slug_rol(rol) for rol in anteriores}
        despues = {slug_rol(rol) for rol in nuevos}
        if set(service._roles(fila)) not in (set(anteriores), set(nuevos)):
            raise problema(
                409, "ROLES_DESINCRONIZADOS", "Los roles institucionales cambiaron."
            )
        key = fila["KeyUsuario"]
        miembro = service._membresia(key)
        if miembro is None or miembro.status != "active":
            raise problema(409, "USUARIO_NO_HABILITADO", "La membresía no está activa.")
        remoto = service._slugs(miembro)
        if remoto not in (antes, despues):
            raise problema(
                409, "ROLES_DESINCRONIZADOS", "Los roles del proveedor cambiaron."
            )
        if remoto != despues:
            with service._workos("update_organization_membership"):
                get_workos().user_management.update_organization_membership(
                    organization_membership_id=miembro.id,
                    **service._parametros_roles_workos(sorted(despues)),
                )
        confirmado = service._membresia(key)
        if (
            confirmado is None
            or confirmado.status != "active"
            or service._slugs(confirmado) != despues
        ):
            raise problema(
                503,
                "ROLES_PENDIENTES_CONFIRMACION",
                "WorkOS aún no confirma los roles.",
            )
        service._revocar_sesiones(key)
        repository.actualizar_rol(conn, id_usuario, ",".join(nuevos))


def operacion() -> Operacion | None:
    settings = get_settings()
    permiso = settings.e104_permiso_aprobar_roles.strip()
    if not settings.e104_politica_roles_activa or not permiso:
        return None
    return Operacion(
        CODIGO,
        TIPO,
        "seguridad",
        frozenset({"ADMIN"}),
        permiso,
        CambioRoles(),
        solicitud_directa=False,
        aplicar_diferido=True,
        validar_aprobador=validar_aprobador,
        contexto_aplicacion=corte_protegido,
    )

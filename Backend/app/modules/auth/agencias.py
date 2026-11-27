"""Asignaciones, matriz de roles y contexto operativo de #450."""

import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import problema
from app.core.database.db import get_engine
from app.core.security.auth import UsuarioActual, codigo_agencia, normalizar_roles
from app.core.security.operador import auditar, exigir_id_interno
from app.modules.auth import agencias_repository as repo
from app.modules.auth import repository as usuarios
from app.modules.auth.agencias_schemas import (
    AgenciaAsignada,
    AsignacionesEntrada,
    AsignacionesUsuario,
    ContextoAgencias,
)
from app.modules.caja import repository as caja

if TYPE_CHECKING:
    from app.core.security.auth import Usuario

MULTIPLES = frozenset(
    {"ADMIN", "SUPERVISOR", "CONTADOR", "AUDITOR", "APROBADOR_CREDITO"}
)
UNICA = frozenset({"ASESOR", "CAJERO"})


def admite_varias(roles: Sequence[str]) -> bool:
    return bool(set(roles) & MULTIPLES) and not bool(set(roles) & UNICA)


def validar_seleccion(
    ids: Sequence[str], principal: str | None, roles: Sequence[str]
) -> None:
    if len(set(ids)) != len(ids) or any(i == "000" for i in ids):
        raise problema(
            422, "ASIGNACIONES_INVALIDAS", "Las agencias deben ser distintas y validas."
        )
    if (ids and principal not in ids) or (not ids and principal is not None):
        raise problema(
            422,
            "PRINCIPAL_NO_ASIGNADA",
            "La agencia principal debe pertenecer a las asignaciones.",
        )
    if len(ids) > 1 and not admite_varias(roles):
        raise problema(
            422,
            "MULTIAGENCIA_NO_PERMITIDA",
            "El rol requiere una sola agencia asignada.",
        )


def validar_matriz(
    roles: Sequence[str], ids: Sequence[str], principal: str | None
) -> None:
    validar_seleccion(ids, principal, roles)


def inicializar(
    conn: Connection, usuario: int, ids: Sequence[str], principal: str, actor: "Usuario"
) -> None:
    actor_id = exigir_id_interno(actor.interno())
    for agencia in ids:
        repo.guardar_asignacion(conn, usuario, agencia, True, actor_id)
        repo.historico(
            conn,
            usuario,
            "ASIGNAR",
            agencia,
            None,
            principal,
            actor_id,
            actor.agencia(),
        )


def sincronizar_traslado(
    conn: Connection, usuario: int, anterior: str | None, nueva: str, actor: "Usuario"
) -> None:
    ids = repo.asignaciones(conn, usuario)
    if len(ids) > 1:
        raise problema(
            409,
            "USAR_ASIGNACIONES_MULTIAGENCIA",
            "Cambie la principal desde las asignaciones multiagencia.",
        )
    actor_id = exigir_id_interno(actor.interno())
    for agencia in set(ids) - {nueva}:
        repo.guardar_asignacion(conn, usuario, agencia, False, actor_id)
        repo.historico(
            conn,
            usuario,
            "REVOCAR",
            agencia,
            anterior,
            nueva,
            actor_id,
            actor.agencia(),
        )
    if nueva not in ids:
        repo.guardar_asignacion(conn, usuario, nueva, True, actor_id)
        repo.historico(
            conn, usuario, "ASIGNAR", nueva, anterior, nueva, actor_id, actor.agencia()
        )
    repo.historico(
        conn, usuario, "PRINCIPAL", None, anterior, nueva, actor_id, actor.agencia()
    )
    if anterior is not None and anterior != nueva:
        repo.trasladar_contextos_vigentes(conn, usuario, anterior, nueva)


def _usuario(conn: Connection, id_: int, bloquear: bool = False):
    fila = usuarios.obtener_usuario(conn, id_, bloquear=bloquear)
    if fila is None:
        raise problema(404, "USUARIO_NO_ENCONTRADO", "El usuario no existe.")
    return fila


def consultar(conn: Connection, coop: Connection, id_: int) -> AsignacionesUsuario:
    fila = _usuario(conn, id_)
    principal = codigo_agencia(fila["AgenciaID"])
    ids = repo.asignaciones(conn, id_)
    catalogo = {a["id_agencia"]: a for a in repo.agencias(coop)}
    agencias = [
        AgenciaAsignada(
            **catalogo.get(i, {"id_agencia": i, "codigo": i, "estado": "I"}),
            principal=i == principal,
        )
        for i in ids
    ]
    return AsignacionesUsuario(
        id_usuario=id_,
        id_agencia_principal=principal,
        agencias=agencias,
        version=repo.version(conn, id_),
    )


def guardar(
    conn: Connection,
    coop: Connection,
    id_: int,
    datos: AsignacionesEntrada,
    actor: "Usuario",
    ip: str,
) -> AsignacionesUsuario:
    actor_id = exigir_id_interno(actor.interno())
    agencia_actor = actor.agencia()
    with auditar(
        "SEG_AUTOGESTION_INTENTO" if actor_id == id_ else "ASIGNAR_AGENCIAS",
        "Organizacion.UsuarioAgencia",
        actor,
        ip,
        "AUT-MULTIAGENCIA",
        str(id_),
    ):
        if actor_id == id_:
            raise problema(
                403,
                "AUTOGESTION_NO_PERMITIDA",
                "No puede cambiar sus propias asignaciones de agencia.",
            )
        try:
            from app.modules.auth.service import (
                bloquear_corte_caja,
                impedir_edicion_durante_recuperacion,
            )

            bloquear_corte_caja(coop)
            fila = _usuario(conn, id_, True)

            impedir_edicion_durante_recuperacion(conn, id_)
            roles = normalizar_roles((fila["RolesWorkOS"] or "").split(","), None)
            validar_seleccion(datos.id_agencias, datos.id_agencia_principal, roles)
            if repo.version(conn, id_) != datos.version:
                raise problema(
                    409,
                    "VERSION_ASIGNACION_DESACTUALIZADA",
                    "Las asignaciones cambiaron. Recarga el usuario antes de guardar.",
                )
            anterior = codigo_agencia(fila["AgenciaID"])
            actuales = set(repo.asignaciones(conn, id_))
            nuevos = set(datos.id_agencias)
            catalogo = {a["id_agencia"]: a for a in repo.agencias(coop)}
            for id_agencia in nuevos:
                if id_agencia not in catalogo or catalogo[id_agencia]["estado"] != "A":
                    raise problema(
                        422,
                        "AGENCIA_INVALIDA",
                        "Una agencia no existe o no esta activa.",
                    )
            jornada = caja.jornada_abierta_de_usuario(coop, id_, bloquear=False)
            if jornada and (
                anterior != datos.id_agencia_principal or actuales != nuevos
            ):
                raise problema(
                    409,
                    "USUARIO_CON_JORNADA_ABIERTA",
                    "Cierre la jornada antes de cambiar las asignaciones.",
                )
            if "CAJERO" in roles and anterior != datos.id_agencia_principal:
                raise problema(
                    409,
                    "CAJERO_TRASLADO_REQUERIDO",
                    "Use el traslado de agencia del cajero para conservar su asignacion vigente.",
                )
            for agencia in sorted(actuales ^ nuevos):
                alta = agencia in nuevos
                repo.guardar_asignacion(conn, id_, agencia, alta, actor_id)
                repo.historico(
                    conn,
                    id_,
                    "ASIGNAR" if alta else "REVOCAR",
                    agencia,
                    anterior,
                    datos.id_agencia_principal,
                    actor_id,
                    agencia_actor,
                )
            if anterior != datos.id_agencia_principal:
                repo.principal(conn, id_, datos.id_agencia_principal)
                repo.historico(
                    conn,
                    id_,
                    "PRINCIPAL",
                    None,
                    anterior,
                    datos.id_agencia_principal,
                    actor_id,
                    agencia_actor,
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return consultar(conn, coop, id_)


def hash_sesion(sid: str) -> bytes:
    return hashlib.sha256(("banking-agencia-v1:" + sid).encode()).digest()


def _alcance(
    conn: Connection, llave: str, roles: Sequence[str]
) -> tuple[int, str | None, list[str]]:
    fila = repo.usuario_por_llave(conn, llave)
    if fila is None or fila["Estado"] != "Activo":
        raise problema(403, "USUARIO_NO_REGISTRADO", "El usuario no esta habilitado.")
    principal = codigo_agencia(fila["AgenciaID"])
    ids = repo.asignaciones(conn, fila["UsuarioID"])
    if not admite_varias(roles):
        ids = [i for i in ids if i == principal]
    return fila["UsuarioID"], principal, ids


def alcance_sesion(llave: str, roles: Sequence[str]) -> tuple[str, ...]:
    try:
        with get_engine("seguridad").connect() as conn:
            return tuple(_alcance(conn, llave, roles)[2])
    except SQLAlchemyError:
        raise problema(
            503,
            "CONTEXTO_AGENCIA_NO_DISPONIBLE",
            "No se pudo verificar el alcance de agencias.",
        ) from None


def _operativas(
    coop: Connection, ids: list[str], roles: Sequence[str]
) -> list[AgenciaAsignada]:
    global_admin = "ADMIN" in roles and not bool(set(roles) & UNICA)
    return [
        AgenciaAsignada(**a)
        for a in repo.agencias(coop)
        if a["estado"] == "A" and (global_admin or a["id_agencia"] in ids)
    ]


def resolver_sesion(llave: str, sid: str, roles: Sequence[str]) -> str | None:
    try:
        with (
            get_engine("seguridad").connect() as conn,
            get_engine("cooperativa").connect() as coop,
        ):
            id_, principal, ids = _alcance(conn, llave, roles)
            permitidas = {a.id_agencia for a in _operativas(coop, ids, roles)}
            contexto = repo.contexto(conn, hash_sesion(sid), id_)
            if contexto:
                return (
                    contexto["agencia"]
                    if contexto["vigente"] and contexto["agencia"] in permitidas
                    else None
                )
            if (
                "ADMIN" in roles and not (set(roles) & UNICA)
            ) or principal not in permitidas:
                return None
            repo.inicializar_contexto(conn, hash_sesion(sid), id_, principal)
            conn.commit()
            confirmado = repo.contexto(conn, hash_sesion(sid), id_)
            return (
                confirmado["agencia"]
                if confirmado
                and confirmado["vigente"]
                and confirmado["agencia"] in permitidas
                else None
            )
    except SQLAlchemyError:
        raise problema(
            503,
            "CONTEXTO_AGENCIA_NO_DISPONIBLE",
            "No se pudo verificar la agencia operativa.",
        ) from None


def contexto_usuario(actor: "Usuario") -> ContextoAgencias:
    id_ = exigir_id_interno(actor.interno())
    with (
        get_engine("seguridad").connect() as conn,
        get_engine("cooperativa").connect() as coop,
    ):
        estado = consultar(conn, coop, id_)
        ids = [a.id_agencia for a in estado.agencias]
        if not admite_varias(actor.roles):
            ids = [i for i in ids if i == estado.id_agencia_principal]
        activa = actor.agencia()
        global_admin = "ADMIN" in actor.roles and not (set(actor.roles) & UNICA)
        global_actual = bool(global_admin)
        permitidas = _operativas(coop, ids, actor.roles)
        activas = {
            a["id_agencia"]: a.get("tipo_agencia")
            for a in repo.agencias(coop)
            if a["estado"] == "A"
        }
        todas = bool(activas) and activas.keys() <= {a.id_agencia for a in permitidas}
        return ContextoAgencias(
            id_agencia=activa,
            agencia_es_matriz=activa is not None and activas.get(activa) == "Matriz",
            id_agencia_principal=estado.id_agencia_principal,
            agencias_asignadas=estado.agencias,
            agencias_permitidas=permitidas,
            requiere_seleccion_agencia=activa is None and not global_actual,
            alcance_global=global_actual,
            acceso_todas_agencias=todas,
        )


def es_matriz_activa(agencia: str) -> bool:
    try:
        with get_engine("cooperativa").connect() as conn:
            return repo.es_matriz(conn, agencia)
    except SQLAlchemyError:
        raise problema(
            503,
            "CONTEXTO_AGENCIA_NO_DISPONIBLE",
            "No se pudo verificar la agencia matriz.",
        ) from None


def exigir_matriz(actor: UsuarioActual) -> None:
    agencia = actor.agencia()
    if agencia is None or not es_matriz_activa(agencia):
        raise problema(
            403, "ACCESO_EXCLUSIVO_MATRIZ", "Seleccione la agencia matriz para acceder."
        )


def seleccionar(
    conn: Connection, coop: Connection, actor: "Usuario", agencia: str | None, ip: str
) -> ContextoAgencias:
    id_ = exigir_id_interno(actor.interno())
    with auditar(
        "CAMBIAR_CONTEXTO",
        "Seguridad.ContextoAgenciaSesion",
        actor,
        ip,
        f"agencia_origen={actor.agencia()} agencia_destino={agencia}",
        str(id_),
    ):
        try:
            _usuario(conn, id_, True)
            _, _, ids = _alcance(conn, actor.id_usuario, actor.roles)
            global_pedido = (
                agencia is None
                and "ADMIN" in actor.roles
                and not (set(actor.roles) & UNICA)
            )
            if not global_pedido and agencia not in {
                a.id_agencia for a in _operativas(coop, ids, actor.roles)
            }:
                raise problema(
                    403,
                    "SIN_ACCESO_AGENCIA",
                    "La agencia no esta autorizada para esta sesion.",
                )
            jornada = caja.jornada_abierta_de_usuario(coop, id_, bloquear=False)
            if jornada and str(jornada["IdAgencia"]).strip() != agencia:
                raise problema(
                    409,
                    "CAJERO_CON_JORNADA_ABIERTA",
                    "Cierre la jornada antes de cambiar de agencia operativa.",
                )
            if global_pedido:
                repo.eliminar_contexto(conn, hash_sesion(actor.id_sesion), id_)
            elif agencia is not None:
                repo.guardar_contexto(conn, hash_sesion(actor.id_sesion), id_, agencia)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    # El objeto Usuario almacena lecturas solo por peticion; forzar resolver despues del cambio.
    actor._leidos.pop("agencia", None)
    return contexto_usuario(actor)


def agencia_consulta_asientos(actor: "Usuario", pedida: str | None) -> str | None:
    """Acceso total usa filtro; alcance parcial queda en la agencia operativa."""
    from app.core.security.operador import agencia_de_consulta, exigir_agencia

    contexto = contexto_usuario(actor)
    if contexto.alcance_global or contexto.acceso_todas_agencias:
        return agencia_de_consulta(actor, pedida)
    actual = exigir_agencia(actor)
    if pedida is not None and pedida != actual:
        raise problema(
            403,
            "AGENCIA_OPERATIVA_REQUERIDA",
            "La consulta debe usar la agencia operativa seleccionada.",
        )
    return actual

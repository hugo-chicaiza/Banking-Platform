"""Inscripción de TAR-01 y resolución por la cola E0-08."""

import json
import logging
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import problema
from app.core.database.db import get_engine
from app.modules.aprobaciones.auditoria import ContextoAuditoria
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.aprobaciones.servicio import Servicio
from app.modules.parametros.service import hoy
from app.modules.tarjetas import repository, service

CODIGO = "TAR-SOLICITAR"
TIPO = "Tarjeta"
logger = logging.getLogger(__name__)


class SolicitudTarjeta:
    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan:
        version = self.version(conn, objetivo)
        if version != "Solicitada" or contenido:
            raise problema(
                409, "TARJETA_NO_SOLICITADA", "La tarjeta debe estar solicitada."
            )
        return Plan({}, {"estado": "Solicitada"}, {"estado": "Generada"}, version)

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        tarjeta = repository.obtener_tarjeta(conn, int(objetivo.id), bloquear=True)
        if (
            tarjeta is None
            or tarjeta["id_agencia"] != objetivo.agencia
            or tarjeta["tipo_tarjeta"] != "Debito"
        ):
            raise problema(
                404,
                "TARJETA_NO_ENCONTRADA",
                "La tarjeta de débito no está disponible en esta agencia.",
            )
        return str(tarjeta["estado_actual"])

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict[str, Any],
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        raise RuntimeError(
            "La aprobación de tarjeta requiere al supervisor acreditado."
        )


def _aprobar(conn: Connection, objetivo: Objetivo, aprobador: int) -> None:
    id_tarjeta = int(objetivo.id)
    with get_engine("seguridad").connect() as seguridad:
        service.aprobar_solicitud_en_cola(conn, seguridad, id_tarjeta, aprobador)
    _cerrar_seguimiento(conn, id_tarjeta)


def _cerrar_seguimiento(conn: Connection, id_tarjeta: int) -> None:
    conn.execute(
        text(
            "UPDATE Tarjeta.SolicitudAprobacionPendiente SET Conciliada=1 WHERE IdTarjeta=:id"
        ),
        {"id": id_tarjeta},
    )


def _descartar(conn: Connection, fila: dict[str, Any]) -> None:
    id_tarjeta = int(fila["IdObjetivo"])
    resolver = fila["IdInternoResolutor"]
    motivo = fila["Comentario"]
    if resolver is None or not motivo:
        raise problema(
            409,
            "RECHAZO_SIN_EVIDENCIA",
            "Faltan el responsable o el motivo del rechazo.",
        )
    service.descartar_solicitud_en_cola(conn, id_tarjeta, resolver, motivo)
    _cerrar_seguimiento(conn, id_tarjeta)


OPERACION = Operacion(
    CODIGO,
    TIPO,
    "cooperativa",
    frozenset({"ADMIN", "ASESOR"}),
    "tar-solicitar:aprobar",
    SolicitudTarjeta(),
    tabla_auditada="Tarjeta.Tarjeta",
    solicitud_directa=False,
    solicitud_unica=True,
    aplicar_con_aprobador=_aprobar,
    cancelable_por_solicitante=False,
    cancelar_por_revocacion=False,
    aplicar_descarte=_descartar,
)


def programar(conn: Connection, id_tarjeta: int, actor: Actor, agencia: str) -> None:
    objetivo = Objetivo(TIPO, str(id_tarjeta), agencia)
    Servicio.puede_solicitar(actor, OPERACION, objetivo)
    conn.execute(
        text("""
            IF NOT EXISTS (SELECT 1 FROM Tarjeta.SolicitudAprobacionPendiente WITH (UPDLOCK,HOLDLOCK)
                           WHERE IdTarjeta=:id)
                INSERT Tarjeta.SolicitudAprobacionPendiente
                    (IdTarjeta,IdOrganizacion,SolicitadoPor,NombreSolicitante,IdInternoSolicitante,RolesSolicitante,IdAgencia)
                VALUES (:id,:org,:sujeto,:nombre,:interno,:roles,:agencia)
        """),
        {
            "id": id_tarjeta,
            "org": actor.organizacion,
            "sujeto": actor.sujeto,
            "nombre": actor.nombre,
            "interno": actor.id_interno,
            "roles": json.dumps(actor.roles),
            "agencia": agencia,
        },
    )


def _cadena_solicitud(conn: Connection, id_tarjeta: int, *, bloquear: bool = False):
    tabla = "Tarjeta.SolicitudAprobacionPendiente"
    if bloquear:
        tabla += " WITH (UPDLOCK,HOLDLOCK)"
    return (
        conn.execute(
            text(f"SELECT * FROM {tabla} WHERE IdTarjeta=:id"), {"id": id_tarjeta}
        )
        .mappings()
        .first()
    )


def id_solicitud(conn: Connection, id_tarjeta: int) -> int | None:
    registro = _cadena_solicitud(conn, id_tarjeta)
    return (
        int(registro["IdSolicitud"]) if registro and registro["IdSolicitud"] else None
    )


def gestionada(conn: Connection, id_tarjeta: int) -> bool:
    return _cadena_solicitud(conn, id_tarjeta) is not None


def _solicitud_en_cola(cola: Servicio, org: str, id_tarjeta: int):
    with cola.seguridad.connect() as seg:
        return (
            seg.execute(
                text("""
                SELECT IdSolicitud,IdObjetivo,IdAgencia,IdInternoSolicitante,IdInternoResolutor,
                       Estado,Comentario,SolicitadoPor
                FROM Seguridad.SolicitudAprobacion
                WHERE IdOrganizacion=:org AND CodigoTransaccion=:codigo AND TipoObjetivo=:tipo AND IdObjetivo=:id
            """),
                {"org": org, "codigo": CODIGO, "tipo": TIPO, "id": str(id_tarjeta)},
            )
            .mappings()
            .one_or_none()
        )


def publicar(cola: Servicio, id_tarjeta: int, contexto: ContextoAuditoria) -> int:
    """La inscripción en CooperativaDB existe antes de intentar escribir en SeguridadDB."""
    with cola.cooperativa.begin() as conn:
        registro = _cadena_solicitud(conn, id_tarjeta, bloquear=True)
        if registro is None:
            raise problema(
                404, "SOLICITUD_NO_ENCONTRADA", "No existe el registro de la solicitud."
            )
        if registro["IdSolicitud"] is not None:
            return int(registro["IdSolicitud"])

        org, agencia = registro["IdOrganizacion"], registro["IdAgencia"].strip()
        previa = _solicitud_en_cola(cola, org, id_tarjeta)
        if previa is not None:
            if (
                (previa["IdAgencia"] or "").strip() != agencia
                or previa["SolicitadoPor"] != registro["SolicitadoPor"]
                or previa["IdInternoSolicitante"] != registro["IdInternoSolicitante"]
            ):
                raise problema(
                    409,
                    "SOLICITUD_INCOMPATIBLE",
                    "Revise la identidad de la solicitud registrada.",
                )
            id_aprobacion = previa["IdSolicitud"]
        else:
            actor = Actor(
                registro["SolicitadoPor"],
                org,
                registro["NombreSolicitante"],
                registro["IdInternoSolicitante"],
                tuple(json.loads(registro["RolesSolicitante"])),
                frozenset(),
                (agencia,),
            )
            id_aprobacion = cola.solicitar(
                actor,
                CODIGO,
                Objetivo(TIPO, str(id_tarjeta), agencia),
                {},
                hoy(),
                contexto,
            )
        conn.execute(
            text(
                "UPDATE Tarjeta.SolicitudAprobacionPendiente SET IdSolicitud=:solicitud WHERE IdTarjeta=:id"
            ),
            {"id": id_tarjeta, "solicitud": id_aprobacion},
        )
        return int(id_aprobacion)


def publicar_al_solicitar(
    cola: Servicio, id_tarjeta: int, contexto: ContextoAuditoria
) -> int | None:
    try:
        return publicar(cola, id_tarjeta, contexto)
    except (HTTPException, SQLAlchemyError) as error:
        logger.warning(
            "tarjetas: inscripción pendiente id_tarjeta=%s tipo=%s",
            id_tarjeta,
            type(error).__name__,
        )
        return None


def reconciliar(cola: Servicio, org: str) -> tuple[int, int, int]:
    with cola.cooperativa.connect() as conn:
        if (
            conn.execute(
                text("SELECT OBJECT_ID('Tarjeta.SolicitudAprobacionPendiente', 'U')")
            ).scalar()
            is None
        ):
            return 0, 0, 0
        pendientes = conn.execute(
            text("""
            SELECT TOP(100) IdTarjeta,IdSolicitud FROM Tarjeta.SolicitudAprobacionPendiente
            WHERE IdOrganizacion=:org AND Conciliada=0
            ORDER BY RevisadaEn,IdTarjeta
        """),
            {"org": org},
        ).all()
    modificadas = errores = 0
    for id_tarjeta, id_aprobacion in pendientes:
        try:
            with cola.cooperativa.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE Tarjeta.SolicitudAprobacionPendiente SET RevisadaEn=SYSUTCDATETIME() WHERE IdTarjeta=:id"
                    ),
                    {"id": id_tarjeta},
                )
            if id_aprobacion is None:
                publicar(cola, id_tarjeta, ContextoAuditoria(canal="SISTEMA"))
                modificadas += 1
            fila = _solicitud_en_cola(cola, org, id_tarjeta)
            if fila is not None and fila["Estado"] in {
                "Rechazada",
                "Cancelada",
                "Fallida",
            }:
                with cola.cooperativa.begin() as conn:
                    if fila["Estado"] == "Rechazada":
                        _descartar(conn, dict(fila))
                    else:
                        _cerrar_seguimiento(conn, id_tarjeta)
                modificadas += 1
        except (HTTPException, SQLAlchemyError):
            errores += 1
    return len(pendientes), modificadas, errores

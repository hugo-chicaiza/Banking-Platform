"""Bandeja atomica para E0-08; el fallo no se oculta ni permite confirmar el cambio."""

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import Connection

from app.modules.aprobaciones.congelacion import congelar
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.repositorio import consulta


@dataclass(frozen=True)
class ContextoAuditoria:
    sesion: str = ""
    origen: str = ""
    correlacion: str = ""
    canal: str = "WEB"
    agencia_actor: str | None = None


def encolar(
    conn: Connection,
    codigo: str,
    actor: Actor | None,
    id_solicitud: int | None,
    agencia: str | None,
    contexto: ContextoAuditoria,
    cambios: dict[str, Any] | None = None,
    resultado: str = "Exitoso",
    *,
    tabla: str = "Seguridad.SolicitudAprobacion",
    objetivo: str | None = None,
) -> None:
    # Los manejadores aceptan solo sus campos declarados. Ningun token ni cookie
    # forma parte del ContextoAuditoria; sesion es el ID del proveedor, no su token.
    contenido = congelar(
        {
            "codigo": codigo,
            "sujeto": actor.sujeto if actor else None,
            "idInterno": actor.id_interno if actor else None,
            "organizacion": actor.organizacion if actor else None,
            "roles": list(actor.roles) if actor else [],
            "agencia": agencia,
            "sesion": contexto.sesion,
            "origen": contexto.origen,
            "correlacion": contexto.correlacion,
            "canal": contexto.canal,
            "tipoObjetivo": "SolicitudAprobacion" if objetivo is None else tabla,
            "tablaAfectada": tabla,
            "agenciaActor": contexto.agencia_actor,
            "idSolicitud": id_solicitud,
            "idObjetivo": objetivo if objetivo is not None else str(id_solicitud),
            "resultado": resultado,
            "cambios": cambios or {},
        }
    ).texto
    conn.execute(
        consulta(
            "INSERT Auditoria.EventoPendiente(IdEvento,CodigoEvento,Contenido) VALUES(:id,:codigo,:contenido)"
        ),
        {"id": str(uuid4()), "codigo": codigo, "contenido": contenido},
    )

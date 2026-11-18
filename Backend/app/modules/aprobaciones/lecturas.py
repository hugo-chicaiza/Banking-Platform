"""Bandejas paginadas con alcance aplicado en SQL, nunca solo en el navegador."""

from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import bindparam

from app.core.api.errors import problema
from app.modules.aprobaciones.congelacion import verificar
from app.modules.aprobaciones.contratos import (
    Bandeja,
    EventoSolicitud,
    Responsable,
    SolicitudDetalle,
    SolicitudResumen,
)
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.repositorio import consulta, obtener
from app.modules.aprobaciones.servicio import Servicio
from app.modules.parametros import general


def _fecha(valor: datetime | None) -> datetime | None:
    return valor.replace(tzinfo=UTC) if valor else None


def resumen(servicio: Servicio, actor: Actor, fila: dict[str, Any]) -> SolicitudResumen:
    try:
        operacion = servicio.registro.obtener(
            fila["CodigoTransaccion"], fila["TipoObjetivo"]
        )
    except HTTPException as error:
        if error.status_code != 404:
            raise
        operacion = None
    ajena = fila["SolicitadoPor"] != actor.sujeto
    pendiente = fila["Estado"] == "Pendiente"
    return SolicitudResumen(
        id_solicitud=fila["IdSolicitud"],
        codigo_transaccion=fila["CodigoTransaccion"],
        tipo_objetivo=fila["TipoObjetivo"],
        id_objetivo=fila["IdObjetivo"],
        id_agencia=fila["IdAgencia"],
        estado=fila["Estado"],
        fecha_solicitud=fila["FechaSolicitud"].replace(tzinfo=UTC),
        solicitante=Responsable(
            sujeto=fila["SolicitadoPor"],
            nombre=fila["NombreSolicitante"],
            id_interno=fila["IdInternoSolicitante"],
        ),
        resolutor=Responsable(
            sujeto=fila["ResueltoPor"],
            nombre=fila["NombreResolutor"],
            id_interno=fila["IdInternoResolutor"],
        )
        if fila["ResueltoPor"]
        else None,
        fecha_resolucion=_fecha(fila["FechaResolucion"]),
        comentario=fila["Comentario"],
        codigo_error=fila["CodigoError"],
        puede_aprobar=pendiente
        and ajena
        and operacion is not None
        and operacion.permiso_aprobacion in actor.permisos,
        puede_rechazar=pendiente
        and ajena
        and operacion is not None
        and operacion.permiso_aprobacion in actor.permisos,
        puede_cancelar=pendiente and not ajena,
    )


def listar(
    servicio: Servicio,
    actor: Actor,
    bandeja: Literal["pendientes", "mias", "resueltas"],
    page: int,
    page_size: int,
    agencia: str | None = None,
) -> Bandeja:
    codigos = [
        o.codigo
        for o in servicio.registro.operaciones()
        if o.permiso_aprobacion in actor.permisos
    ]
    sql = consulta("""SELECT *,COUNT(*) OVER() AS TotalFiltrado FROM Seguridad.SolicitudAprobacion
        WHERE IdOrganizacion=:org
        AND (:global=1 OR IdAgencia IS NULL OR IdAgencia IN :agencias)
        AND (:agencia IS NULL OR IdAgencia IS NULL OR IdAgencia=:agencia)
        AND (SolicitadoPor=:actor OR CodigoTransaccion IN :codigos)
        AND ((:bandeja='mias' AND SolicitadoPor=:actor)
          OR (:bandeja='pendientes' AND Estado='Pendiente' AND SolicitadoPor<>:actor AND CodigoTransaccion IN :codigos)
          OR (:bandeja='resueltas' AND Estado NOT IN('Pendiente','Aprobada')))
        ORDER BY FechaSolicitud DESC,IdSolicitud DESC OFFSET :offset ROWS FETCH NEXT :limite ROWS ONLY""").bindparams(
        bindparam("agencias", expanding=True), bindparam("codigos", expanding=True)
    )
    args = {
        "org": actor.organizacion,
        "global": int(actor.global_admin),
        "agencias": list(actor.agencias),
        "agencia": agencia,
        "actor": actor.sujeto,
        "codigos": codigos,
        "bandeja": bandeja,
        "offset": (page - 1) * page_size,
        "limite": page_size,
    }
    with servicio.seguridad.connect() as seg:
        filas = seg.execute(sql, args).mappings().all()
        primera = (
            filas[0]
            if filas
            else (
                seg.execute(sql, {**args, "offset": 0, "limite": 1}).mappings().first()
                if page > 1
                else None
            )
        )
        pendientes = (
            seg.execute(
                sql, {**args, "bandeja": "pendientes", "offset": 0, "limite": 1}
            )
            .mappings()
            .first()
        )
    with servicio.cooperativa.connect() as coop:
        dias = general.valor(
            coop,
            "APR_DIAS_RESALTAR",
            datetime.now(ZoneInfo("America/Guayaquil")).date(),
        )
    if not isinstance(dias, int) or isinstance(dias, bool):
        raise problema(
            503, "PARAMETRO_INVALIDO", "El umbral de antiguedad no es valido."
        )
    return Bandeja(
        items=[resumen(servicio, actor, dict(f)) for f in filas],
        total=primera["TotalFiltrado"] if primera else 0,
        page=page,
        page_size=page_size,
        pendientes_para_mi=pendientes["TotalFiltrado"] if pendientes else 0,
        dias_resaltar=dias,
    )


def detalle(servicio: Servicio, actor: Actor, id_: int) -> SolicitudDetalle:
    with servicio.seguridad.connect() as seg:
        fila = obtener(seg, id_, actor.organizacion)
        actor.alcance(fila["IdAgencia"])
        if fila["SolicitadoPor"] != actor.sujeto:
            operacion = servicio.registro.obtener(
                fila["CodigoTransaccion"], fila["TipoObjetivo"]
            )
            autorizado = operacion.permiso_aprobacion in actor.permisos
        else:
            autorizado = True
        if not autorizado:
            raise problema(
                404, "SOLICITUD_NO_ENCONTRADA", "La solicitud no esta disponible."
            )
        contenido = verificar(fila["Contenido"], bytes(fila["HashContenido"]))
        eventos = (
            seg.execute(
                consulta(
                    "SELECT * FROM Seguridad.SolicitudAprobacionEvento WHERE IdSolicitud=:id ORDER BY IdEvento"
                ),
                {"id": id_},
            )
            .mappings()
            .all()
        )
    return SolicitudDetalle(
        **resumen(servicio, actor, fila).model_dump(),
        antes=contenido["antes"],
        despues=contenido["despues"],
        eventos=[
            EventoSolicitud(
                estado_anterior=e["EstadoAnterior"],
                estado_nuevo=e["EstadoNuevo"],
                responsable=Responsable(
                    sujeto=e["Sujeto"], nombre=e["Nombre"], id_interno=e["IdInterno"]
                )
                if e["Sujeto"]
                else None,
                comentario=e["Comentario"],
                fecha_evento=e["FechaEvento"].replace(tzinfo=UTC),
            )
            for e in eventos
        ],
    )

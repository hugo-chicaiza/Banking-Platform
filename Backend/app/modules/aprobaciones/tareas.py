"""Ejecutor E0-08 con bloqueo SQL por tarea y registro persistido de resultados."""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import bindparam
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.integrations.workos_client import get_organizacion_id
from app.modules.aprobaciones.auditoria import ContextoAuditoria
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.aprobaciones.motores import motor
from app.modules.aprobaciones.relevo import alertar_pendientes, entregar
from app.modules.aprobaciones.repositorio import consulta
from app.modules.aprobaciones.servicio import Servicio
from app.modules.parametros import general

CODIGOS = ("APR_RECUPERACION", "APR_RESUMEN_ANTIGUAS", "APR_AUD_RELEVO")


@dataclass
class Conteo:
    procesados: int = 0
    modificados: int = 0
    errores: int = 0


def recuperar(servicio: Servicio, org: str) -> Conteo:
    resultado = Conteo()
    contexto = ContextoAuditoria(canal="SISTEMA")
    with servicio.seguridad.connect() as seg:
        filas = (
            seg.execute(
                consulta(
                    "SELECT * FROM Seguridad.SolicitudAprobacion WHERE IdOrganizacion=:org AND CodigoTransaccion IN :codigos AND Estado IN('Pendiente','Aprobada') ORDER BY FechaSolicitud,IdSolicitud"
                ).bindparams(bindparam("codigos", expanding=True)),
                {
                    "org": org,
                    "codigos": [o.codigo for o in servicio.registro.operaciones()],
                },
            )
            .mappings()
            .all()
        )
    for fila in filas:
        resultado.procesados += 1
        try:
            if fila["Estado"] == "Aprobada":
                # Continuacion de una decision ya autorizada, no una nueva aprobacion.
                # El comprobante en la base destino impide ejecutar dos veces.
                servicio.ejecutar(fila["IdSolicitud"], org, None, contexto)
                resultado.modificados += 1
                continue
            operacion = servicio.registro.obtener(
                fila["CodigoTransaccion"], fila["TipoObjetivo"]
            )
            try:
                solicitante = servicio.identidad_vigente(fila["SolicitadoPor"], org)
                servicio.puede_solicitar(
                    solicitante, operacion, servicio._objetivo(dict(fila))
                )
            except HTTPException as error:
                if error.status_code not in (403, 404):
                    raise
                servicio.cancelar_sistema(
                    fila["IdSolicitud"], org, "SOLICITANTE_SIN_PERMISO", contexto
                )
                resultado.modificados += 1
        except HTTPException:
            # Una indisponibilidad de WorkOS nunca se interpreta como revocacion.
            resultado.errores += 1
    if get_settings().e104_recuperar_correo:
        from app.modules.auth import recuperacion_correo

        for id_, usuario in recuperacion_correo.pendientes(servicio.seguridad):
            resultado.procesados += 1
            try:
                recuperacion_correo.reconciliar(servicio.seguridad, id_, usuario)
            except (HTTPException, SQLAlchemyError):
                recuperacion_correo.registrar_error(servicio.seguridad, id_)
                resultado.errores += 1
            else:
                resultado.modificados += 1
    return resultado


def resumir(servicio: Servicio, org: str) -> Conteo:
    fecha = datetime.now(ZoneInfo("America/Guayaquil")).date()
    with servicio.cooperativa.connect() as coop:
        dias = general.valor(coop, "APR_DIAS_RESALTAR", fecha)
    if not isinstance(dias, int) or isinstance(dias, bool) or dias < 1:
        raise problema(
            503, "PARAMETRO_INVALIDO", "No se pudo obtener el umbral de antiguedad."
        )
    with servicio.seguridad.begin() as seg:
        filas = (
            seg.execute(
                consulta("""SELECT IdSolicitud,IdAgencia,CodigoTransaccion FROM Seguridad.SolicitudAprobacion
            WHERE IdOrganizacion=:org AND Estado='Pendiente' AND FechaSolicitud<=DATEADD(day,-:dias,SYSUTCDATETIME())
            ORDER BY FechaSolicitud,IdSolicitud"""),
                {"org": org, "dias": dias},
            )
            .mappings()
            .all()
        )
        contenido = json.dumps(
            {
                "diasResaltar": dias,
                "cantidad": len(filas),
                "solicitudes": [
                    {
                        "idSolicitud": f["IdSolicitud"],
                        "idAgencia": f["IdAgencia"],
                        "operacion": f["CodigoTransaccion"],
                    }
                    for f in filas
                ],
            },
            separators=(",", ":"),
        )
        existe = seg.execute(
            consulta(
                "SELECT 1 FROM Sistema.ResumenAprobaciones WITH(UPDLOCK,HOLDLOCK) WHERE IdOrganizacion=:org AND Fecha=:fecha"
            ),
            {"org": org, "fecha": fecha},
        ).scalar()
        if existe:
            seg.execute(
                consulta(
                    "UPDATE Sistema.ResumenAprobaciones SET Contenido=:contenido,FechaActualizacionUTC=SYSUTCDATETIME() WHERE IdOrganizacion=:org AND Fecha=:fecha"
                ),
                {"org": org, "fecha": fecha, "contenido": contenido},
            )
        else:
            seg.execute(
                consulta(
                    "INSERT Sistema.ResumenAprobaciones(IdOrganizacion,Fecha,Contenido,FechaActualizacionUTC) VALUES(:org,:fecha,:contenido,SYSUTCDATETIME())"
                ),
                {"org": org, "fecha": fecha, "contenido": contenido},
            )
    return Conteo(len(filas), 1)


def ejecutar(
    servicio: Servicio,
    org: str,
    codigo: str,
    sujeto_manual: str | None = None,
    motivo: str | None = None,
) -> Conteo:
    if codigo not in CODIGOS or (
        sujeto_manual is not None and not (motivo or "").strip()
    ):
        raise problema(422, "TAREA_INVALIDA", "La tarea o el motivo no son validos.")
    with servicio.seguridad.connect() as control:
        bloqueo = control.execute(
            consulta(
                "DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource=:recurso,@LockMode='Exclusive',@LockOwner='Session',@LockTimeout=0; SELECT @r"
            ),
            {"recurso": codigo + ":" + org},
        ).scalar_one()
        control.commit()
        if bloqueo < 0:
            raise problema(409, "TAREA_EN_EJECUCION", "La tarea ya esta en ejecucion.")
        id_ = None
        resultado = Conteo()
        estado = "Fallido"
        codigo_error = None
        try:
            tarea = (
                control.execute(
                    consulta(
                        "SELECT Estado,PermiteManual FROM Sistema.Tarea WHERE Codigo=:codigo"
                    ),
                    {"codigo": codigo},
                )
                .mappings()
                .first()
            )
            if (
                tarea is None
                or tarea["Estado"] != "A"
                or (sujeto_manual is not None and not tarea["PermiteManual"])
            ):
                raise problema(
                    409, "TAREA_NO_DISPONIBLE", "La tarea no esta habilitada."
                )
            id_ = control.execute(
                consulta(
                    "INSERT Sistema.TareaEjecucion(Codigo,EjecutadaPor,Motivo) OUTPUT inserted.IdEjecucion VALUES(:codigo,:sujeto,:motivo)"
                ),
                {"codigo": codigo, "sujeto": sujeto_manual, "motivo": motivo},
            ).scalar_one()
            control.commit()
            if codigo == "APR_RECUPERACION":
                resultado = recuperar(servicio, org)
            elif codigo == "APR_RESUMEN_ANTIGUAS":
                resultado = resumir(servicio, org)
            else:
                n = entregar(servicio.cooperativa, servicio.seguridad) + entregar(
                    servicio.seguridad, servicio.seguridad
                )
                resultado = Conteo(n, n)
                # E0-05 (M8 AC 13): alerta si lo pendiente más antiguo supera la edad máxima
                alertar_pendientes(servicio.cooperativa, servicio.seguridad)
            estado = "Parcial" if resultado.errores else "Exitoso"
            codigo_error = "TAREA_PARCIAL" if resultado.errores else None
            return resultado
        except Exception:
            codigo_error = "TAREA_ERROR"
            raise
        finally:
            try:
                if control.in_transaction():
                    control.rollback()
                if id_ is not None:
                    control.execute(
                        consulta(
                            "UPDATE Sistema.TareaEjecucion SET FinUTC=SYSUTCDATETIME(),Resultado=:resultado,Procesados=:procesados,Modificados=:modificados,CodigoError=:error WHERE IdEjecucion=:id"
                        ),
                        {
                            "id": id_,
                            "resultado": estado,
                            "procesados": resultado.procesados,
                            "modificados": resultado.modificados,
                            "error": codigo_error,
                        },
                    )
                    control.commit()
            finally:
                try:
                    if control.in_transaction():
                        control.rollback()
                    control.execute(
                        consulta(
                            "EXEC sys.sp_releaseapplock @Resource=:recurso,@LockOwner='Session'"
                        ),
                        {"recurso": codigo + ":" + org},
                    )
                    control.commit()
                except SQLAlchemyError:
                    control.invalidate()
                    raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("codigo", choices=CODIGOS)
    args = parser.parse_args()
    servicio = Servicio(motor("seguridad"), motor("cooperativa"), registro_inicial())
    resultado = ejecutar(servicio, get_organizacion_id(), args.codigo)
    print(
        json.dumps(
            {
                "codigo": args.codigo,
                "procesados": resultado.procesados,
                "modificados": resultado.modificados,
                "errores": resultado.errores,
            }
        )
    )


if __name__ == "__main__":
    main()

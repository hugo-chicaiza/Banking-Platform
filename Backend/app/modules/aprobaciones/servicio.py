"""Doble autorizacion persistida y ejecucion con comprobante transaccional."""

import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from hmac import compare_digest
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import problema
from app.modules.aprobaciones import identidad
from app.modules.aprobaciones import repositorio as repo
from app.modules.aprobaciones.auditoria import ContextoAuditoria, encolar
from app.modules.aprobaciones.congelacion import congelar, verificar
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.registro import Objetivo, Operacion, Registro


class Servicio:
    def __init__(
        self,
        seguridad: Engine,
        cooperativa: Engine,
        registro: Registro,
        resolver: Callable[[str, str], Actor] = identidad.vigente,
    ):
        self.seguridad = seguridad
        self.cooperativa = cooperativa
        self.registro = registro
        self.identidad_vigente = resolver

    @staticmethod
    def puede_solicitar(actor: Actor, operacion: Operacion, objetivo: Objetivo) -> None:
        actor.alcance(objetivo.agencia)
        if (
            operacion.permiso_ejecucion
            and operacion.permiso_ejecucion not in actor.permisos
        ):
            raise problema(
                403,
                "SIN_PERMISO",
                "Falta el permiso efectivo para solicitar esta operacion.",
            )
        if not set(actor.roles) & operacion.roles_ejecucion:
            raise problema(
                403, "SIN_PERMISO", "Falta el acceso de ejecucion de la operacion."
            )

    def _motor(self, operacion: Operacion) -> Engine:
        return self.seguridad if operacion.base == "seguridad" else self.cooperativa

    @staticmethod
    def _objetivo(fila: dict[str, Any]) -> Objetivo:
        return Objetivo(fila["TipoObjetivo"], fila["IdObjetivo"], fila["IdAgencia"])

    def _catalogo(self, conn, operacion: Operacion) -> None:
        fila = (
            conn.execute(
                repo.consulta(
                    "SELECT * FROM Seguridad.TransaccionesInterfaz WITH(UPDLOCK,HOLDLOCK) WHERE CodigoTransaccion=:codigo AND Estado='A'"
                ),
                {"codigo": operacion.codigo},
            )
            .mappings()
            .first()
        )
        if (
            fila is None
            or fila["BaseObjetivo"] != operacion.base
            or fila["PermisoAprobacion"] != operacion.permiso_aprobacion
            or set(json.loads(fila["RolesEjecucion"])) != operacion.roles_ejecucion
        ):
            raise problema(
                503,
                "OPERACION_NO_CONFIGURADA",
                "La configuracion de la operacion requiere revision.",
            )

    def solicitar(
        self,
        actor: Actor,
        codigo: str,
        objetivo: Objetivo,
        contenido: dict[str, Any],
        hoy: date,
        contexto: ContextoAuditoria,
    ) -> int:
        operacion = self.registro.obtener(codigo, objetivo.tipo)
        self.puede_solicitar(actor, operacion, objetivo)
        with self.seguridad.begin() as seg:
            self._catalogo(seg, operacion)
            if operacion.aplicar_diferido:
                operacion.manejador.version(seg, objetivo)
            existe = seg.execute(
                repo.consulta("""SELECT IdSolicitud FROM Seguridad.SolicitudAprobacion WITH(UPDLOCK,HOLDLOCK)
                WHERE IdOrganizacion=:org AND CodigoTransaccion=:codigo AND TipoObjetivo=:tipo AND IdObjetivo=:objetivo
                AND (IdAgencia=:agencia OR (IdAgencia IS NULL AND :agencia IS NULL)) AND (EnCurso=1 OR :unica=1)"""),
                {
                    "org": actor.organizacion,
                    "codigo": codigo,
                    "tipo": objetivo.tipo,
                    "objetivo": objetivo.id,
                    "agencia": objetivo.agencia,
                    "unica": operacion.solicitud_unica,
                },
            ).scalar()
            if existe is not None:
                raise problema(
                    409,
                    "SOLICITUD_YA_PENDIENTE",
                    "Ya existe una solicitud en curso para ese objetivo.",
                )
            if operacion.base == "seguridad":
                plan = operacion.manejador.preparar(seg, objetivo, contenido, hoy)
            else:
                with self.cooperativa.begin() as coop:
                    plan = operacion.manejador.preparar(coop, objetivo, contenido, hoy)
            congelado = congelar(
                {
                    "cambio": plan.contenido,
                    "antes": plan.antes,
                    "despues": plan.despues,
                    "version": plan.version,
                }
            )
            id_ = int(
                seg.execute(
                    repo.consulta("""INSERT Seguridad.SolicitudAprobacion
                (IdOrganizacion,CodigoTransaccion,TipoObjetivo,IdObjetivo,IdAgencia,Contenido,HashContenido,Antes,Despues,VersionObjetivo,SolicitadoPor,NombreSolicitante,IdInternoSolicitante)
                OUTPUT inserted.IdSolicitud VALUES(:org,:codigo,:tipo,:objetivo,:agencia,:contenido,:hash,:antes,:despues,:version,:actor,:nombre,:interno)"""),
                    {
                        "org": actor.organizacion,
                        "codigo": codigo,
                        "tipo": objetivo.tipo,
                        "objetivo": objetivo.id,
                        "agencia": objetivo.agencia,
                        "contenido": congelado.texto,
                        "hash": congelado.huella,
                        "antes": json.dumps(plan.antes, ensure_ascii=False),
                        "despues": json.dumps(plan.despues, ensure_ascii=False),
                        "version": plan.version,
                        "actor": actor.sujeto,
                        "nombre": actor.nombre,
                        "interno": actor.id_interno,
                    },
                ).scalar_one()
            )
            repo.evento(
                seg,
                id_,
                None,
                "Pendiente",
                actor.sujeto,
                actor.nombre,
                actor.id_interno,
            )
            encolar(seg, "APR_SOLICITUD_CREADA", actor, id_, objetivo.agencia, contexto)
        return id_

    def _intento_propio(
        self, actor: Actor, id_: int, contexto: ContextoAuditoria
    ) -> None:
        with self.seguridad.begin() as seg:
            fila = repo.obtener(seg, id_, actor.organizacion)
            encolar(
                seg,
                "APR_AUTOAPROBACION_INTENTO",
                actor,
                id_,
                fila["IdAgencia"],
                contexto,
                resultado="Fallido",
            )

    def aprobar(
        self,
        actor: Actor,
        id_: int,
        comentario: str | None,
        contexto: ContextoAuditoria,
    ) -> dict[str, Any]:
        with self.seguridad.connect() as seg:
            fila = repo.obtener(seg, id_, actor.organizacion)
        actor.alcance(fila["IdAgencia"])
        if (
            actor.sujeto == fila["SolicitadoPor"]
            or actor.id_interno == fila["IdInternoSolicitante"]
        ):
            self._intento_propio(actor, id_, contexto)
            raise problema(
                403, "APROBADOR_ES_SOLICITANTE", "Debe aprobar otra persona."
            )
        operacion = self.registro.obtener(
            fila["CodigoTransaccion"], fila["TipoObjetivo"]
        )
        if not operacion.permite_aprobar(actor):
            raise problema(
                403, "SIN_PERMISO", "Falta el permiso efectivo de aprobacion."
            )
        if operacion.validar_aprobador is not None:
            operacion.validar_aprobador(self._objetivo(fila), actor.id_interno)
        try:
            solicitante = self.identidad_vigente(
                fila["SolicitadoPor"], actor.organizacion
            )
            self.puede_solicitar(solicitante, operacion, self._objetivo(fila))
        except HTTPException as error:
            if error.status_code not in (403, 404):
                raise
            if not operacion.cancelar_por_revocacion:
                raise problema(
                    409,
                    "SOLICITANTE_SIN_PERMISO",
                    "El solicitante perdió acceso. Revise la solicitud o rechácela con un motivo.",
                ) from None
            self.cancelar_sistema(
                id_, actor.organizacion, "SOLICITANTE_SIN_PERMISO", contexto
            )
            raise problema(
                409,
                "SOLICITANTE_SIN_PERMISO",
                "La solicitud se cancelo por perdida de acceso del solicitante.",
            ) from None
        with self.seguridad.begin() as seg:
            self._catalogo(seg, operacion)
            fila = repo.obtener(seg, id_, actor.organizacion, True)
            repo.pendiente(fila)
            verificar(fila["Contenido"], bytes(fila["HashContenido"]))
            seg.execute(
                repo.consulta("""UPDATE Seguridad.SolicitudAprobacion SET Estado='Aprobada',ResueltoPor=:actor,
                NombreResolutor=:nombre,IdInternoResolutor=:interno,FechaResolucion=SYSUTCDATETIME(),Comentario=:comentario
                WHERE IdSolicitud=:id AND Estado='Pendiente'"""),
                {
                    "id": id_,
                    "actor": actor.sujeto,
                    "nombre": actor.nombre,
                    "interno": actor.id_interno,
                    "comentario": comentario,
                },
            )
            repo.evento(
                seg,
                id_,
                "Pendiente",
                "Aprobada",
                actor.sujeto,
                actor.nombre,
                actor.id_interno,
                comentario,
            )
            encolar(
                seg,
                "APR_SOLICITUD_RESUELTA",
                actor,
                id_,
                fila["IdAgencia"],
                contexto,
                {
                    "solicitante": fila["SolicitadoPor"],
                    "estado": "Aprobada",
                    "idSolicitud": id_,
                },
            )
            if operacion.base == "seguridad" and not operacion.aplicar_diferido:
                self._aplicar(seg, fila, operacion, actor, contexto)
                self._terminar(seg, fila, actor, contexto)
                return {"idSolicitud": id_, "estado": "Ejecutada"}
        return self.ejecutar(id_, actor.organizacion, actor, contexto)

    def _aplicar(
        self,
        conn,
        fila: dict[str, Any],
        operacion: Operacion,
        actor: Actor | None,
        contexto: ContextoAuditoria,
    ) -> None:
        lock = conn.execute(
            repo.consulta("""DECLARE @resultado int;
            EXEC @resultado=sys.sp_getapplock @Resource=:recurso,@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=15000;
            SELECT @resultado"""),
            {
                "recurso": "APR:"
                + fila["IdOrganizacion"]
                + ":"
                + str(fila["IdSolicitud"])
            },
        ).scalar_one()
        if lock < 0:
            raise problema(
                503, "APROBACION_OCUPADA", "La solicitud esta siendo recuperada."
            )
        contenido = verificar(fila["Contenido"], bytes(fila["HashContenido"]))
        comprobante = conn.execute(
            repo.consulta(
                "SELECT HashContenido FROM Seguridad.AprobacionAplicada WHERE IdOrganizacion=:org AND IdSolicitud=:id"
            ),
            {"org": fila["IdOrganizacion"], "id": fila["IdSolicitud"]},
        ).scalar()
        if comprobante is not None:
            if not compare_digest(bytes(comprobante), bytes(fila["HashContenido"])):
                raise problema(
                    409,
                    "CONTENIDO_ALTERADO",
                    "El comprobante no coincide con la solicitud.",
                )
            return
        objetivo = self._objetivo(fila)
        if operacion.aplicar_diferido:
            solicitante = self.identidad_vigente(
                fila["SolicitadoPor"], fila["IdOrganizacion"]
            )
            resolutor = self.identidad_vigente(
                fila["ResueltoPor"], fila["IdOrganizacion"]
            )
            self.puede_solicitar(solicitante, operacion, objetivo)
            resolutor.alcance(objetivo.agencia)
            if (
                resolutor.sujeto == solicitante.sujeto
                or resolutor.id_interno == solicitante.id_interno
                or not operacion.permite_aprobar(resolutor)
            ):
                raise problema(
                    403, "SIN_PERMISO", "La aprobación ya no está autorizada."
                )
            if operacion.validar_aprobador is not None:
                operacion.validar_aprobador(objetivo, resolutor.id_interno)
        if operacion.manejador.version(conn, objetivo) != fila["VersionObjetivo"]:
            raise problema(
                409,
                "SOLICITUD_DESACTUALIZADA",
                "El objetivo cambio desde la solicitud.",
            )
        if operacion.aplicar_con_aprobador is not None:
            if actor is None or actor.id_interno != fila["IdInternoResolutor"]:
                raise RuntimeError("No se pudo acreditar al aprobador de la operacion.")
            operacion.aplicar_con_aprobador(conn, objetivo, actor.id_interno)
        else:
            operacion.manejador.aplicar(
                conn,
                objetivo,
                contenido["cambio"],
                fila["SolicitadoPor"],
                fila["IdSolicitud"],
            )
        conn.execute(
            repo.consulta(
                "INSERT Seguridad.AprobacionAplicada(IdOrganizacion,IdSolicitud,HashContenido,CodigoTransaccion) VALUES(:org,:id,:hash,:codigo)"
            ),
            {
                "org": fila["IdOrganizacion"],
                "id": fila["IdSolicitud"],
                "hash": fila["HashContenido"],
                "codigo": fila["CodigoTransaccion"],
            },
        )
        encolar(
            conn,
            operacion.evento_ejecucion(contenido["cambio"])
            if callable(operacion.evento_ejecucion)
            else operacion.evento_ejecucion,
            actor,
            fila["IdSolicitud"],
            fila["IdAgencia"],
            contexto,
            {
                "solicitante": fila["SolicitadoPor"],
                "aprobador": actor.sujeto if actor else fila["ResueltoPor"],
                "antes": contenido["antes"],
                "despues": contenido["despues"],
                **(
                    {"motivo": contenido["cambio"].get("motivo")}
                    if operacion.tabla_auditada
                    else {}
                ),
            },
            tabla=operacion.tabla_auditada or "Seguridad.SolicitudAprobacion",
            objetivo=objetivo.id if operacion.tabla_auditada else None,
        )

    @staticmethod
    def _terminar(
        seg, fila: dict[str, Any], actor: Actor | None, contexto: ContextoAuditoria
    ) -> None:
        seg.execute(
            repo.consulta(
                "UPDATE Seguridad.SolicitudAprobacion SET Estado='Ejecutada',EnCurso=0,CodigoError=NULL WHERE IdSolicitud=:id AND Estado='Aprobada'"
            ),
            {"id": fila["IdSolicitud"]},
        )
        repo.evento(
            seg,
            fila["IdSolicitud"],
            "Aprobada",
            "Ejecutada",
            actor.sujeto if actor else None,
            actor.nombre if actor else None,
            actor.id_interno if actor else None,
        )
        encolar(
            seg,
            "APR_SOLICITUD_RESUELTA",
            actor,
            fila["IdSolicitud"],
            fila["IdAgencia"],
            contexto,
            {"estado": "Ejecutada"},
        )

    def _evidencia_aprobacion(
        self, fila: dict[str, Any], contexto: ContextoAuditoria
    ) -> tuple[Actor, ContextoAuditoria]:
        with self.seguridad.connect() as seg:
            registro = seg.execute(
                repo.consulta("""SELECT TOP(1) Contenido FROM Auditoria.EventoPendiente
                    WHERE CodigoEvento='APR_SOLICITUD_RESUELTA'
                    AND JSON_VALUE(Contenido,'$.idObjetivo')=:id
                    AND JSON_VALUE(Contenido,'$.organizacion')=:org
                    AND JSON_VALUE(Contenido,'$.sujeto')=:aprobador
                    AND JSON_VALUE(Contenido,'$.cambios.estado')='Aprobada'
                    ORDER BY FechaCreacionUTC"""),
                {
                    "id": str(fila["IdSolicitud"]),
                    "org": fila["IdOrganizacion"],
                    "aprobador": fila["ResueltoPor"],
                },
            ).scalar()
        if registro is None:
            raise problema(
                503, "APROBACION_SIN_EVIDENCIA", "Falta la evidencia del aprobador."
            )
        evidencia = json.loads(registro)
        actor = Actor(
            fila["ResueltoPor"],
            fila["IdOrganizacion"],
            fila["NombreResolutor"],
            fila["IdInternoResolutor"],
            tuple(evidencia["roles"]),
            frozenset(),
            (),
        )
        return actor, replace(
            contexto,
            sesion=evidencia["sesion"],
            origen=evidencia["origen"],
            correlacion=evidencia["correlacion"],
            agencia_actor=evidencia.get("agenciaActor"),
        )

    def ejecutar(
        self, id_: int, org: str, actor: Actor | None, contexto: ContextoAuditoria
    ) -> dict[str, Any]:
        with self.seguridad.connect() as seg:
            fila = repo.obtener(seg, id_, org)
        if fila["Estado"] == "Ejecutada":
            return {"idSolicitud": id_, "estado": "Ejecutada"}
        if fila["Estado"] != "Aprobada":
            raise problema(
                409,
                "SOLICITUD_NO_PENDIENTE",
                "La solicitud no esta pendiente de aplicacion.",
            )
        operacion = self.registro.obtener(
            fila["CodigoTransaccion"], fila["TipoObjetivo"]
        )
        if actor is None and operacion.tabla_auditada:
            actor, contexto = self._evidencia_aprobacion(fila, contexto)
        try:
            contexto_externo = operacion.contexto_aplicacion or nullcontext
            with contexto_externo(), self._motor(operacion).begin() as conn:
                self._aplicar(conn, fila, operacion, actor, contexto)
        except HTTPException as error:
            if operacion.aplicar_diferido:
                with self.seguridad.begin() as seg:
                    seg.execute(
                        repo.consulta("""
                            UPDATE Seguridad.SolicitudAprobacion
                            SET Intentos=Intentos+1,CodigoError='APROBACION_PENDIENTE_RECUPERACION'
                            WHERE IdSolicitud=:id AND IdOrganizacion=:org AND Estado='Aprobada'
                        """),
                        {"id": id_, "org": org},
                    )
                raise problema(
                    503,
                    "APROBACION_PENDIENTE_RECUPERACION",
                    "La solicitud aprobada requiere conciliación antes de cerrarse.",
                ) from None
            if error.status_code not in (400, 401, 403, 404, 409, 422):
                raise
            with self.seguridad.begin() as seg:
                actual = repo.obtener(seg, id_, org, True)
                if actual["Estado"] == "Aprobada":
                    detalle_error: Any = error.detail
                    codigo = (
                        str(
                            cast(dict[str, Any], detalle_error).get(
                                "code", "APLICACION_RECHAZADA"
                            )
                        )
                        if isinstance(detalle_error, dict)
                        else "APLICACION_RECHAZADA"
                    )
                    seg.execute(
                        repo.consulta(
                            "UPDATE Seguridad.SolicitudAprobacion SET Estado='Fallida',EnCurso=0,CodigoError=:error WHERE IdSolicitud=:id"
                        ),
                        {"id": id_, "error": codigo},
                    )
                    repo.evento(
                        seg,
                        id_,
                        "Aprobada",
                        "Fallida",
                        actor.sujeto if actor else None,
                        actor.nombre if actor else None,
                        actor.id_interno if actor else None,
                        codigo,
                    )
                    encolar(
                        seg,
                        "APR_SOLICITUD_RESUELTA",
                        actor,
                        id_,
                        fila["IdAgencia"],
                        contexto,
                        {"estado": "Fallida", "codigo": codigo},
                        "Fallido",
                    )
            raise
        except SQLAlchemyError:
            raise problema(
                503,
                "APROBACION_PENDIENTE_RECUPERACION",
                "La solicitud aprobada requiere recuperacion; no la vuelva a crear.",
            ) from None
        try:
            with self.seguridad.begin() as seg:
                actual = repo.obtener(seg, id_, org, True)
                if actual["Estado"] == "Aprobada":
                    self._terminar(seg, actual, actor, contexto)
        except SQLAlchemyError:
            raise problema(
                503,
                "APROBACION_PENDIENTE_RECUPERACION",
                "La operacion tiene comprobante; falta confirmar su cierre. No cree otra solicitud.",
            ) from None
        return {"idSolicitud": id_, "estado": "Ejecutada"}

    def resolver(
        self,
        actor: Actor,
        id_: int,
        estado: str,
        comentario: str,
        contexto: ContextoAuditoria,
    ) -> dict[str, Any]:
        if estado not in ("Rechazada", "Cancelada"):
            raise ValueError("Resolucion no valida")
        with self.seguridad.begin() as seg:
            fila = repo.obtener(seg, id_, actor.organizacion, True)
            actor.alcance(fila["IdAgencia"])
            repo.pendiente(fila)
            if estado == "Cancelada":
                operacion = self.registro.buscar(
                    fila["CodigoTransaccion"], fila["TipoObjetivo"]
                )
                if operacion is not None and not operacion.cancelable_por_solicitante:
                    raise problema(
                        403, "SIN_PERMISO", "La solicitud debe resolverla otra persona."
                    )
                if actor.sujeto != fila["SolicitadoPor"]:
                    raise problema(
                        403, "SIN_PERMISO", "Solo el solicitante puede cancelar."
                    )
                resolutor = None
            else:
                operacion = self.registro.obtener(
                    fila["CodigoTransaccion"], fila["TipoObjetivo"]
                )
                if (
                    actor.sujeto == fila["SolicitadoPor"]
                    or actor.id_interno == fila["IdInternoSolicitante"]
                    or not operacion.permite_aprobar(actor)
                ):
                    raise problema(
                        403,
                        "SIN_PERMISO",
                        "Se requiere otra persona con acceso de aprobacion.",
                    )
                if not comentario.strip():
                    raise problema(
                        422, "COMENTARIO_REQUERIDO", "El comentario es obligatorio."
                    )
                resolutor = actor.sujeto
            seg.execute(
                repo.consulta("""UPDATE Seguridad.SolicitudAprobacion SET Estado=:estado,EnCurso=0,ResueltoPor=:resolutor,
                NombreResolutor=:nombre,IdInternoResolutor=:interno,FechaResolucion=SYSUTCDATETIME(),Comentario=:comentario WHERE IdSolicitud=:id AND Estado='Pendiente'"""),
                {
                    "id": id_,
                    "estado": estado,
                    "resolutor": resolutor,
                    "nombre": actor.nombre,
                    "interno": actor.id_interno,
                    "comentario": comentario,
                },
            )
            repo.evento(
                seg,
                id_,
                "Pendiente",
                estado,
                actor.sujeto,
                actor.nombre,
                actor.id_interno,
                comentario,
            )
            encolar(
                seg,
                "APR_SOLICITUD_CANCELADA"
                if estado == "Cancelada"
                else "APR_SOLICITUD_RESUELTA",
                actor,
                id_,
                fila["IdAgencia"],
                contexto,
                {"estado": estado},
            )
        if operacion is not None and operacion.aplicar_descarte is not None:
            try:
                with self._motor(operacion).begin() as conn:
                    operacion.aplicar_descarte(
                        conn,
                        {
                            **fila,
                            "Estado": estado,
                            "Comentario": comentario,
                            "IdInternoResolutor": actor.id_interno,
                        },
                    )
            except (HTTPException, SQLAlchemyError):
                raise problema(
                    503,
                    "RECHAZO_PENDIENTE_RECUPERACION",
                    "La decisión quedó registrada y su aplicación continúa en segundo plano.",
                ) from None
        return {"idSolicitud": id_, "estado": estado}

    def cancelar_sistema(
        self, id_: int, org: str, motivo: str, contexto: ContextoAuditoria
    ) -> None:
        with self.seguridad.begin() as seg:
            fila = repo.obtener(seg, id_, org, True)
            if fila["Estado"] != "Pendiente":
                return
            seg.execute(
                repo.consulta(
                    "UPDATE Seguridad.SolicitudAprobacion SET Estado='Cancelada',EnCurso=0,FechaResolucion=SYSUTCDATETIME(),CodigoError=:error WHERE IdSolicitud=:id AND Estado='Pendiente'"
                ),
                {"id": id_, "error": motivo},
            )
            repo.evento(seg, id_, "Pendiente", "Cancelada", None, None, None, motivo)
            encolar(
                seg,
                "APR_SOLICITUD_CANCELADA",
                None,
                id_,
                fila["IdAgencia"],
                contexto,
                {"motivo": motivo},
            )

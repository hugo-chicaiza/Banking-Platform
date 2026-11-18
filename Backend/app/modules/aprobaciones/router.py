"""API de aprobaciones con identidad efectiva y contexto multiagencia existentes."""

from datetime import datetime
from functools import lru_cache
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import ConfigDict, Field, field_validator

from app.core.api.errors import ProblemDetailsRoute, problema
from app.core.api.middleware import ip_cliente, obtener_trace_id
from app.core.api.schemas import CamelModel
from app.core.security.auth import UsuarioActual, require_auth
from app.modules.aprobaciones import identidad, lecturas
from app.modules.aprobaciones.auditoria import ContextoAuditoria
from app.modules.aprobaciones.contratos import (
    Aprobacion,
    Bandeja,
    Rechazo,
    SolicitudAceptada,
    SolicitudDetalle,
)
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.aprobaciones.motores import motor
from app.modules.aprobaciones.registro import Objetivo
from app.modules.aprobaciones.scheduler import lifespan
from app.modules.aprobaciones.servicio import Servicio

router = APIRouter(
    prefix="/aprobaciones",
    tags=["Aprobaciones"],
    route_class=ProblemDetailsRoute,
    dependencies=[Depends(require_auth)],
    lifespan=lifespan,
)
Id = Annotated[int, Path(alias="idSolicitud", gt=0, le=9223372036854775807)]


class Solicitar(CamelModel):
    model_config = ConfigDict(extra="forbid")
    codigo_transaccion: str = Field(
        min_length=1, max_length=20, pattern=r"^[A-Z0-9-]+$"
    )
    tipo_objetivo: str = Field(min_length=1, max_length=40)
    id_objetivo: str = Field(min_length=1, max_length=60)
    id_agencia: str | None = Field(default=None, pattern=r"^[0-9]{3}$")
    contenido: dict[str, Any]

    @field_validator("id_agencia")
    @classmethod
    def agencia_valida(cls, valor: str | None) -> str | None:
        if valor == "000":
            raise ValueError("La agencia 000 no es valida.")
        return valor


@lru_cache
def servicio() -> Servicio:
    return Servicio(motor("seguridad"), motor("cooperativa"), registro_inicial())


def actual(usuario: UsuarioActual) -> Actor:
    if not usuario.id_organizacion:
        raise problema(
            403, "ORGANIZACION_NO_AUTORIZADA", "La sesion no tiene organizacion."
        )
    return identidad.vigente(usuario.id_usuario, usuario.id_organizacion)


Actual = Annotated[Actor, Depends(actual)]
Cola = Annotated[Servicio, Depends(servicio)]


def contexto(request: Request, usuario: UsuarioActual) -> ContextoAuditoria:
    return ContextoAuditoria(
        usuario.id_sesion,
        ip_cliente(request.scope),
        obtener_trace_id(request.scope),
        agencia_actor=usuario.agencia(),
    )


def alcance_operativo(actor: Actor, usuario, agencia: str | None) -> None:
    actor.alcance(agencia)
    if not actor.global_admin and agencia is not None and usuario.agencia() != agencia:
        raise problema(
            404,
            "SOLICITUD_NO_ENCONTRADA",
            "El recurso no corresponde a la agencia operativa.",
        )


@router.get("/accesos")
def accesos(actor: Actual, cola: Cola, usuario: UsuarioActual) -> dict[str, Any]:
    propia = lecturas.listar(
        cola, actor, "mias", 1, 1, None if actor.global_admin else usuario.agencia()
    )
    creador = any(
        set(actor.roles) & op.roles_ejecucion for op in cola.registro.operaciones()
    )
    aprobador = any(
        op.permiso_aprobacion in actor.permisos for op in cola.registro.operaciones()
    )
    return {
        "puedeVer": creador or aprobador or propia.total > 0,
        "puedeSolicitar": creador,
        "pendientesParaMi": propia.pendientes_para_mi,
        "diasResaltar": propia.dias_resaltar,
    }


@router.get("", response_model=Bandeja)
def bandeja(
    actor: Actual,
    cola: Cola,
    usuario: UsuarioActual,
    bandeja: Literal["pendientes", "mias", "resueltas"] = "pendientes",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> Bandeja:
    return lecturas.listar(
        cola,
        actor,
        bandeja,
        page,
        page_size,
        None if actor.global_admin else usuario.agencia(),
    )


@router.post("", status_code=202, response_model=SolicitudAceptada)
def solicitar(
    datos: Solicitar,
    actor: Actual,
    cola: Cola,
    usuario: UsuarioActual,
    request: Request,
) -> SolicitudAceptada:
    operacion = cola.registro.obtener(datos.codigo_transaccion, datos.tipo_objetivo)
    if not operacion.solicitud_directa:
        raise problema(
            403, "SIN_PERMISO", "Use la ruta de la operacion para solicitar el cambio."
        )
    alcance_operativo(actor, usuario, datos.id_agencia)
    id_ = cola.solicitar(
        actor,
        datos.codigo_transaccion,
        Objetivo(datos.tipo_objetivo, datos.id_objetivo, datos.id_agencia),
        datos.contenido,
        datetime.now(ZoneInfo("America/Guayaquil")).date(),
        contexto(request, usuario),
    )
    return SolicitudAceptada(id_solicitud=id_)


@router.get("/{idSolicitud}", response_model=SolicitudDetalle)
def ficha(
    id_: Id, actor: Actual, cola: Cola, usuario: UsuarioActual
) -> SolicitudDetalle:
    datos = lecturas.detalle(cola, actor, id_)
    alcance_operativo(actor, usuario, datos.id_agencia)
    return datos


def comprobar_agencia(id_: int, actor: Actor, cola: Servicio, usuario) -> None:
    datos = lecturas.detalle(cola, actor, id_)
    alcance_operativo(actor, usuario, datos.id_agencia)


@router.post("/{idSolicitud}/aprobar")
def aprobar(
    id_: Id,
    datos: Aprobacion,
    actor: Actual,
    cola: Cola,
    usuario: UsuarioActual,
    request: Request,
) -> dict[str, Any]:
    comprobar_agencia(id_, actor, cola, usuario)
    return cola.aprobar(actor, id_, datos.comentario, contexto(request, usuario))


@router.post("/{idSolicitud}/rechazar")
def rechazar(
    id_: Id,
    datos: Rechazo,
    actor: Actual,
    cola: Cola,
    usuario: UsuarioActual,
    request: Request,
) -> dict[str, Any]:
    comprobar_agencia(id_, actor, cola, usuario)
    return cola.resolver(
        actor, id_, "Rechazada", datos.comentario, contexto(request, usuario)
    )


@router.post("/{idSolicitud}/cancelar")
def cancelar(
    id_: Id,
    datos: Aprobacion,
    actor: Actual,
    cola: Cola,
    usuario: UsuarioActual,
    request: Request,
) -> dict[str, Any]:
    comprobar_agencia(id_, actor, cola, usuario)
    return cola.resolver(
        actor,
        id_,
        "Cancelada",
        datos.comentario or "Cancelada por el solicitante",
        contexto(request, usuario),
    )

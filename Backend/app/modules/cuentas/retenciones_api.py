from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import Connection

from app.core.api.errors import ProblemDetailsRoute, problema
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, require_permiso
from app.modules.aprobaciones import router as apr
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.registro import Objetivo
from app.modules.cuentas import retenciones as r
from app.modules.cuentas import retenciones_aprobacion as a
from app.modules.parametros.service import hoy

router = APIRouter(route_class=ProblemDetailsRoute, tags=["cuentas"])
IdCuenta = Annotated[int, Path(gt=0, le=2147483647)]
IdRetencion = Annotated[int, Path(gt=0, le=9223372036854775807)]
Db = Annotated[Connection, Depends(cooperativa)]
Gestor = Annotated[Usuario, Depends(require_permiso(a.PERMISO))]


def alcance(usuario: Usuario) -> str:
    agencia = usuario.agencia()
    if agencia is None:
        raise problema(403, "AGENCIA_REQUERIDA", "Seleccione una agencia activa.")
    return agencia


@router.get("/cuentas/{idCuenta}/retenciones", operation_id="CTAConsultarRetenciones")
def listar(idCuenta: IdCuenta, conn: Db, usuario: Gestor) -> list[r.Retencion]:
    return r.listar(conn, idCuenta, alcance(usuario))


@router.post(
    "/cuentas/{idCuenta}/retenciones",
    operation_id="CTASolicitarRetencion",
    status_code=202,
)
def solicitar(
    idCuenta: IdCuenta,
    datos: r.Alta,
    request: Request,
    usuario: Gestor,
    actor: apr.Actual,
    cola: apr.Cola,
) -> SolicitudAceptada:
    id_ = cola.solicitar(
        actor,
        a.ALTA,
        Objetivo("CuentaRetencion", str(idCuenta), alcance(usuario)),
        {"datos": datos.model_dump(mode="json"), "actor": actor.id_interno},
        hoy(),
        apr.contexto(request, usuario),
    )
    return SolicitudAceptada(id_solicitud=id_)


@router.post(
    "/cuentas/{idCuenta}/retenciones/{idRet}/liberacion",
    operation_id="CTASolicitarLiberacion",
    status_code=202,
)
def liberar(
    idCuenta: IdCuenta,
    idRet: IdRetencion,
    datos: r.Liberacion,
    request: Request,
    usuario: Gestor,
    actor: apr.Actual,
    cola: apr.Cola,
) -> SolicitudAceptada:
    id_ = cola.solicitar(
        actor,
        a.LIBERACION,
        Objetivo("Retencion", f"{idCuenta}:{idRet}", alcance(usuario)),
        {"motivo": datos.motivo, "actor": actor.id_interno},
        hoy(),
        apr.contexto(request, usuario),
    )
    return SolicitudAceptada(id_solicitud=id_)

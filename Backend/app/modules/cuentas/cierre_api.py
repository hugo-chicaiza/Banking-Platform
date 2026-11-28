"""API de lista de verificación, solicitud y certificado de cierre E6-07."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy import Connection

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, problema
from app.core.database.db import cooperativa
from app.core.pdf import respuesta_pdf, respuestas_pdf
from app.core.security.auth import Usuario, require_auth, require_roles
from app.modules.aprobaciones import router as aprobaciones
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.registro import Objetivo
from app.modules.cuentas import cierre
from app.modules.parametros.service import hoy

router = APIRouter(
    tags=["cuentas"],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]
IdCuenta = Annotated[int, Path(gt=0, le=2147483647)]
_ROLES_CONSULTA = ("ASESOR", "SUPERVISOR", "ADMIN", "CUMPLIMIENTO")
_ROLES_SOLICITAR = ("ASESOR", "ADMIN")
Lector = Annotated[Usuario, Depends(require_roles(*_ROLES_CONSULTA))]
Solicitante = Annotated[Usuario, Depends(require_roles(*_ROLES_SOLICITAR))]


def _agencia(usuario: Usuario) -> str:
    agencia = usuario.agencia()
    if agencia is None:
        raise problema(403, "AGENCIA_REQUERIDA", "Seleccione una agencia activa.")
    return agencia


@router.get(
    "/cuentas/{idCuenta}/cierre",
    operation_id="CTACierreLista",
    response_model=cierre.ListaCierre,
    openapi_extra={"x-roles": list(_ROLES_CONSULTA)},
)
def consultar_lista_cierre(
    idCuenta: IdCuenta,
    usuario: Lector,
    conn: Db,
    cola: aprobaciones.Cola,
) -> cierre.ListaCierre:
    return cierre.lista_cierre(
        conn, idCuenta, _agencia(usuario), seguridad=cola.seguridad
    )


@router.post(
    "/cuentas/{idCuenta}/cierre",
    operation_id="CTACierreSolicitar",
    response_model=SolicitudAceptada,
    status_code=202,
    openapi_extra={"x-roles": list(_ROLES_SOLICITAR)},
)
def solicitar_cierre(
    idCuenta: IdCuenta,
    datos: cierre.SolicitarCierre,
    usuario: Solicitante,
    request: Request,
    actor: aprobaciones.Actual,
    cola: aprobaciones.Cola,
) -> SolicitudAceptada:
    agencia = _agencia(usuario)
    solicitud = cola.solicitar(
        actor,
        cierre.CODIGO,
        Objetivo(cierre.TIPO, str(idCuenta), agencia),
        datos.model_dump(mode="json", by_alias=True),
        hoy(),
        aprobaciones.contexto(request, usuario),
    )
    return SolicitudAceptada(id_solicitud=solicitud)


@router.get(
    "/cuentas/{idCuenta}/certificado-cierre",
    operation_id="CTACertificadoCierre",
    responses={**RESPUESTAS_ERROR, **respuestas_pdf("Certificado de cierre de cuenta")},
    openapi_extra={"x-roles": list(_ROLES_CONSULTA)},
)
def descargar_certificado_cierre(
    idCuenta: IdCuenta, usuario: Lector, conn: Db
) -> Response:
    agencia = _agencia(usuario)
    contenido = cierre.certificado_cierre(conn, idCuenta, agencia, usuario.nombre)
    return respuesta_pdf(contenido, f"certificado-cierre-{idCuenta}.pdf")

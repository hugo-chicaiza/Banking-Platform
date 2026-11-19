"""Consulta, ejemplo sin reserva y solicitud de reglas E3-04."""

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import Connection, text

from app.core.api.errors import ProblemDetailsRoute, problema
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, UsuarioActual, require_auth, require_permiso
from app.modules.aprobaciones import router as apr
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.motores import motor
from app.modules.aprobaciones.registro import Objetivo
from app.modules.parametros.service import hoy
from app.modules.productos import numeracion as n
from app.modules.productos import numeracion_aprobacion as aprobacion
from app.modules.productos.numeracion_formato import formar_numero
from app.modules.productos.numeracion_schemas import (
    EjemploEntrada,
    EjemploVista,
    NumeracionVista,
    ReglaEntrada,
    ReglaVista,
)
from app.modules.productos.programacion import subproducto

router = APIRouter(
    route_class=ProblemDetailsRoute, dependencies=[Depends(require_auth)]
)
Id = Annotated[int, Path(gt=0, le=2147483647)]
Db = Annotated[Connection, Depends(cooperativa)]
Lector = Annotated[Usuario, Depends(require_permiso("prd-consultar"))]


def proponente(
    usuario: Annotated[Usuario, Depends(require_permiso("prd-numeracion"))],
    actor: apr.Actual,
) -> Usuario:
    if "prd-numeracion" not in actor.permisos or "ADMIN" not in actor.roles:
        raise problema(
            403,
            "SIN_PERMISO",
            "Falta el permiso efectivo para solicitar reglas de numeracion.",
        )
    return usuario


Proponente = Annotated[Usuario, Depends(proponente)]


def comprobar_modelo(conn: Connection, id_sub: int) -> None:
    fila = subproducto(conn, id_sub, permitir_retirado=True)
    if fila["TipoProducto"] != "Cuenta":
        raise problema(
            422,
            "TIPO_PRODUCTO_INVALIDO",
            "La numeracion corresponde a subproductos de cuenta.",
        )


def ejemplo(
    conn: Connection, id_sub: int, regla: ReglaEntrada, agencia: str | None = None
) -> EjemploVista:
    if agencia is None:
        agencia = conn.execute(
            text(
                "SELECT TOP(1) IdAgencia FROM Organizacion.Agencia WHERE Estado='A' AND LEN(IdAgencia)=3 AND IdAgencia NOT LIKE '%[^0-9]%' ORDER BY IdAgencia"
            )
        ).scalar()
    if regla.incluye_agencia and agencia is None:
        return EjemploVista(
            ejemplo=None, estado_secuencia="SIN_AGENCIA", agencia_ejemplo=None
        )
    if (
        regla.incluye_agencia
        and not conn.execute(
            text(
                "SELECT 1 FROM Organizacion.Agencia WHERE IdAgencia=:id AND Estado='A'"
            ),
            {"id": agencia},
        ).scalar()
    ):
        raise problema(
            422, "AGENCIA_INACTIVA", "La agencia del ejemplo no esta disponible."
        )
    raiz = n.serie_compatible(conn, regla, id_sub)
    ultimo = (
        conn.execute(
            text(
                "SELECT UltimoNumero FROM ProductosFinancieros.SecuenciaCuenta WHERE IdReglaNumeracion=:id"
            ),
            {"id": raiz},
        ).scalar()
        if raiz
        else n.inicial(conn, regla)
    )
    if ultimo is None:
        raise problema(409, "SECUENCIA_NO_DISPONIBLE", "El contador requiere revision.")
    if ultimo >= 10**regla.longitud_secuencia - 1:
        return EjemploVista(
            ejemplo=None, estado_secuencia="AGOTADA", agencia_ejemplo=agencia
        )
    return EjemploVista(
        ejemplo=formar_numero(regla, int(ultimo) + 1, agencia or ""),
        estado_secuencia="DISPONIBLE",
        agencia_ejemplo=agencia,
    )


def vista(fila: dict, autores: dict[int, str]) -> ReglaVista:
    return ReglaVista(
        **n.configuracion(fila).model_dump(),
        id_regla_numeracion=fila["IdReglaNumeracion"],
        usada=bool(fila["Usada"]),
        vigencia_desde=fila["VigenciaDesde"],
        vigencia_hasta=fila["VigenciaHasta"],
        fecha_creacion=fila["FechaCreacion"].replace(tzinfo=UTC),
        id_solicitud=fila["IdSolicitud"],
        estado=fila["Estado"],
        responsable=autores.get(
            fila["IdSolicitud"],
            "Configuracion inicial"
            if fila["IdSolicitud"] is None
            else "Registro previo",
        ),
    )


@router.get("/subproductos/{id_sub}/numeracion", response_model=NumeracionVista)
def consultar(
    id_sub: Id, _: Lector, usuario: UsuarioActual, conn: Db
) -> NumeracionVista:
    comprobar_modelo(conn, id_sub)
    filas = n.reglas(conn, id_sub)
    actual = n.vigente(conn, id_sub)
    datos = (
        ejemplo(conn, id_sub, n.configuracion(actual))
        if actual
        else EjemploVista(
            ejemplo=None, estado_secuencia="SIN_REGLA", agencia_ejemplo=None
        )
    )
    usada = any(v["Usada"] for v in filas) or n.cuentas_existentes(conn, id_sub)
    conn.rollback()
    with motor("seguridad").connect() as seg:
        solicitudes = (
            seg.execute(
                text(
                    "SELECT IdSolicitud,NombreSolicitante,IdInternoSolicitante,Estado FROM Seguridad.SolicitudAprobacion WHERE IdOrganizacion=:org AND CodigoTransaccion=:codigo AND TipoObjetivo='SubProducto' AND IdObjetivo=:id ORDER BY IdSolicitud DESC"
                ),
                {
                    "org": usuario.id_organizacion,
                    "codigo": aprobacion.CODIGO,
                    "id": str(id_sub),
                },
            )
            .mappings()
            .all()
        )
    autores = {
        v["IdSolicitud"]: f"{v['NombreSolicitante']}({v['IdInternoSolicitante']})"
        for v in solicitudes
    }
    pendiente = next(
        (
            v["IdSolicitud"]
            for v in solicitudes
            if v["Estado"] in ("Pendiente", "Aprobada")
        ),
        None,
    )
    return NumeracionVista(
        **datos.model_dump(),
        regla=vista(actual, autores) if actual else None,
        usada=usada,
        historial=[vista(v, autores) for v in reversed(filas)],
        solicitud_pendiente=pendiente,
    )


@router.post("/subproductos/{id_sub}/numeracion/ejemplo", response_model=EjemploVista)
def previsualizar(
    id_sub: Id, datos: EjemploEntrada, _: Proponente, conn: Db
) -> EjemploVista:
    comprobar_modelo(conn, id_sub)
    return ejemplo(conn, id_sub, datos.regla, datos.id_agencia)


@router.put(
    "/subproductos/{id_sub}/numeracion",
    status_code=202,
    response_model=SolicitudAceptada,
)
def solicitar(
    id_sub: Id,
    datos: ReglaEntrada,
    request: Request,
    _: Proponente,
    usuario: UsuarioActual,
    actor: apr.Actual,
    cola: apr.Cola,
) -> SolicitudAceptada:
    id_solicitud = cola.solicitar(
        actor,
        aprobacion.CODIGO,
        Objetivo("SubProducto", str(id_sub), None),
        datos.model_dump(mode="json", by_alias=True),
        hoy(),
        apr.contexto(request, usuario),
    )
    return SolicitudAceptada(id_solicitud=id_solicitud)

"""Endpoints E3-05: clases, asignaciones, resolución por subproducto y solicitud de cambios."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import Connection, text

from app.core.api.errors import ProblemDetailsRoute, problema
from app.core.api.schemas import CamelModel
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, UsuarioActual, require_auth, require_permiso
from app.modules.aprobaciones import router as apr
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.motores import motor
from app.modules.aprobaciones.registro import Objetivo
from app.modules.catalogos.subproductos import tipo_tarjeta_de
from app.modules.contabilidad import cuentas_producto as cp
from app.modules.parametros.service import hoy

router = APIRouter(
    route_class=ProblemDetailsRoute, dependencies=[Depends(require_auth)]
)
Id = Annotated[int, Path(gt=0, le=2147483647)]
Db = Annotated[Connection, Depends(cooperativa)]
Lector = Annotated[Usuario, Depends(require_permiso("prd-consultar"))]


class Clase(CamelModel):
    id_clase: int
    id_tipo_producto: int
    codigo_tipo_producto: str
    id_tipo_credito: int | None
    codigo_tipo_credito: str | None
    codigo_rol: str
    nombre_rol: str
    situacion: str | None
    condicion: str | None
    tramo: int | None
    cuenta_base: str
    nombre_cuenta_base: str | None
    nivel: Literal["TIPO", "PRODUCTO"]
    obligatorio: bool
    solo_con_tasa: bool


class Asignacion(CamelModel):
    id_cuenta_producto: int
    id_clase: int
    id_producto: int | None
    codigo_producto: str | None
    id_sub_producto: int | None
    codigo_sub_producto: str | None
    id_cuenta_contable: int
    codigo_cuenta: str
    nombre_cuenta: str
    vigencia_desde: date
    vigencia_hasta: date | None
    id_solicitud: int | None


class ProductoDelTipo(CamelModel):
    id_producto: int
    codigo_producto: str
    nombre_producto: str
    id_tipo_credito: int | None


class SubproductoDelTipo(CamelModel):
    id_sub_producto: int
    id_producto: int
    codigo_sub_producto: str
    nombre_sub_producto: str


class AsignacionesVista(CamelModel):
    asignaciones: list[Asignacion]
    productos: list[ProductoDelTipo]
    subproductos: list[SubproductoDelTipo]
    solicitud_pendiente: int | None


class Resuelta(Clase):
    requerido: bool
    origen: Literal["TIPO", "PRODUCTO", "SUBPRODUCTO"] | None
    cuenta: Asignacion | None


class SubproductoCuentas(CamelModel):
    id_sub_producto: int
    codigo_sub_producto: str
    id_tipo_producto: int
    tipo_tarjeta: str | None
    aviso: str | None
    faltantes: list[str]
    roles: list[Resuelta]


def _clase(k: dict) -> dict:
    return {
        "id_clase": k["IdClase"],
        "id_tipo_producto": k["IdTipoProducto"],
        "codigo_tipo_producto": k["CodigoTipoProducto"],
        "id_tipo_credito": k["IdTipoCredito"],
        "codigo_tipo_credito": k["CodigoTipoCredito"],
        "codigo_rol": k["CodigoRol"],
        "nombre_rol": k["NombreRol"],
        "situacion": k["Situacion"],
        "condicion": k["Condicion"],
        "tramo": k["Tramo"],
        "cuenta_base": k["CuentaBase"],
        "nombre_cuenta_base": k["NombreCuentaBase"],
        "nivel": k["Nivel"],
        "obligatorio": bool(k["Obligatorio"]),
        "solo_con_tasa": bool(k["SoloConTasa"]),
    }


def _asignacion(a: dict) -> dict:
    return {
        "id_cuenta_producto": a["IdCuentaProducto"],
        "id_clase": a["IdClase"],
        "id_producto": a["IdProducto"],
        "codigo_producto": a["CodigoProducto"],
        "id_sub_producto": a["IdSubProducto"],
        "codigo_sub_producto": a["CodigoSubProducto"],
        "id_cuenta_contable": a["IdCuentaContable"],
        "codigo_cuenta": a["CodigoCuenta"],
        "nombre_cuenta": a["NombreCuenta"],
        "vigencia_desde": a["VigenciaDesde"],
        "vigencia_hasta": a["VigenciaHasta"],
        "id_solicitud": a["IdSolicitud"],
    }


def proponente(
    usuario: Annotated[Usuario, Depends(require_permiso("con-cuenta-editar"))],
    actor: apr.Actual,
) -> Usuario:
    if "con-cuenta-editar" not in actor.permisos or "CONTADOR" not in actor.roles:
        raise problema(
            403,
            "SIN_PERMISO",
            "Falta el permiso efectivo para asignar cuentas contables.",
        )
    return usuario


Proponente = Annotated[Usuario, Depends(proponente)]


@router.get("/cuentas-producto/clases", response_model=list[Clase])
def listar_clases(
    _: Lector,
    conn: Db,
    id_tipo_producto: Annotated[
        int | None, Query(alias="idTipoProducto", gt=0, le=2147483647)
    ] = None,
) -> list[dict]:
    """Roles contables de cada tipo de producto y la cuenta bajo la que se asignan."""
    return [_clase(k) for k in cp.clases(conn, id_tipo_producto)]


@router.get("/cuentas-producto/tipos/{id_tipo}", response_model=AsignacionesVista)
def listar_asignaciones(
    id_tipo: Id,
    _: Lector,
    usuario: UsuarioActual,
    conn: Db,
    fecha: date | None = None,
) -> dict:
    """Asignaciones vigentes y programadas de un tipo, con la solicitud en curso."""
    cp._tipo(conn, id_tipo)
    filas = cp.asignaciones(conn, id_tipo, fecha or hoy())
    productos, subproductos = cp.productos_del_tipo(conn, id_tipo)
    conn.rollback()
    with motor("seguridad").connect() as seg:
        pendiente = seg.execute(
            text(
                "SELECT TOP (1) IdSolicitud FROM Seguridad.SolicitudAprobacion WHERE IdOrganizacion=:org AND CodigoTransaccion=:codigo AND TipoObjetivo='TipoProducto' AND IdObjetivo=:id AND Estado IN ('Pendiente','Aprobada') ORDER BY IdSolicitud DESC"
            ),
            {"org": usuario.id_organizacion, "codigo": cp.CODIGO, "id": str(id_tipo)},
        ).scalar()
    return {
        "asignaciones": [_asignacion(a) for a in filas],
        "productos": productos,
        "subproductos": subproductos,
        "solicitud_pendiente": pendiente,
    }


@router.get(
    "/cuentas-producto/subproductos/{id_sub}", response_model=SubproductoCuentas
)
def cuentas_de_subproducto(
    id_sub: Id, _: Lector, conn: Db, fecha: date | None = None
) -> dict:
    """Cuentas que se aplican al subproducto y el nivel del que vienen."""
    dia = fecha or hoy()
    sub, filas = cp.resolver(conn, id_sub, dia)
    tarjeta = (
        tipo_tarjeta_de(sub["CodigoSubProducto"])
        if sub["CodigoTipoProducto"] == "TARJETA"
        else None
    )
    return {
        "id_sub_producto": id_sub,
        "codigo_sub_producto": sub["CodigoSubProducto"],
        "id_tipo_producto": sub["IdTipoProducto"],
        "tipo_tarjeta": tarjeta,
        "aviso": cp.AVISO_TARJETA_CREDITO if tarjeta == "Credito" else None,
        "faltantes": sorted(
            {f["CodigoRol"] for f in filas if f["Requerido"] and f["Cuenta"] is None}
        ),
        "roles": [
            {
                **_clase(f),
                "requerido": f["Requerido"],
                "origen": f["Origen"],
                "cuenta": _asignacion(f["Cuenta"]) if f["Cuenta"] else None,
            }
            for f in filas
        ],
    }


@router.put(
    "/cuentas-producto/tipos/{id_tipo}",
    status_code=202,
    response_model=SolicitudAceptada,
)
def solicitar(
    id_tipo: Id,
    datos: cp.Solicitud,
    request: Request,
    _: Proponente,
    usuario: UsuarioActual,
    actor: apr.Actual,
    cola: apr.Cola,
) -> SolicitudAceptada:
    """Cambios de asignación: quedan pendientes hasta que otra persona los apruebe."""
    id_solicitud = cola.solicitar(
        actor,
        cp.CODIGO,
        Objetivo("TipoProducto", str(id_tipo), None),
        datos.model_dump(mode="json", by_alias=True),
        hoy(),
        apr.contexto(request, usuario),
    )
    return SolicitudAceptada(id_solicitud=id_solicitud)

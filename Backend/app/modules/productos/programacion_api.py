"""Endpoints E3-03 reutilizando identidad y cola E0-08."""

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import Connection, text

from app.core.api.errors import ProblemDetailsRoute, problema
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, UsuarioActual, require_auth, require_permiso
from app.modules.aprobaciones import router as apr
from app.modules.aprobaciones.congelacion import verificar
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.motores import motor
from app.modules.aprobaciones.registro import Objetivo
from app.modules.parametros.service import hoy
from app.modules.productos import programacion as p
from app.modules.productos.programacion_schemas import (
    Cambio,
    CondicionNueva,
    CuposNuevos,
    FinRestriccion,
    RestriccionNueva,
)

router = APIRouter(
    route_class=ProblemDetailsRoute, dependencies=[Depends(require_auth)]
)
Id = Annotated[int, Path(gt=0, le=2147483647)]
Lector = Annotated[Usuario, Depends(require_permiso("prd-consultar"))]
Proponente = Annotated[Usuario, Depends(require_permiso("prd-condicion"))]
Db = Annotated[Connection, Depends(cooperativa)]


def solicitar(
    id_sub: int, cambio: Cambio, request, usuario, actor, cola
) -> SolicitudAceptada:
    if "prd-condicion" not in actor.permisos:
        raise problema(
            403, "SIN_PERMISO", "Falta el permiso efectivo de condiciones de productos."
        )
    id_ = cola.solicitar(
        actor,
        p.CODIGO,
        Objetivo("SubProducto", str(id_sub), None),
        cambio.model_dump(mode="json", by_alias=True),
        hoy(),
        apr.contexto(request, usuario),
    )
    return SolicitudAceptada(id_solicitud=id_)


def leer(id_sub, conn, usuario):
    conjuntos = p.historia(conn, id_sub, permitir_retirado=True)
    conn.rollback()  # Solo lectura: liberar el catalogo antes de consultar la otra base.
    with motor("seguridad").connect() as seg:
        solicitudes = [
            dict(f)
            for f in seg.execute(
                text(
                    "SELECT IdSolicitud,Estado,FechaSolicitud,NombreSolicitante,IdInternoSolicitante,Contenido,HashContenido FROM Seguridad.SolicitudAprobacion WHERE IdOrganizacion=:org AND CodigoTransaccion=:codigo AND TipoObjetivo='SubProducto' AND IdObjetivo=:id ORDER BY IdSolicitud DESC"
                ),
                {"org": usuario.id_organizacion, "codigo": p.CODIGO, "id": str(id_sub)},
            ).mappings()
        ]
    autores = {
        f[
            "IdSolicitud"
        ]: f"{f['NombreSolicitante'] or 'Usuario'}({f['IdInternoSolicitante']})"
        for f in solicitudes
    }
    publicas = []
    for f in solicitudes:
        contenido = verificar(f["Contenido"], bytes(f["HashContenido"]))["cambio"]
        publicas.append(
            {
                "idSolicitud": f["IdSolicitud"],
                "estado": f["Estado"],
                "fecha": f["FechaSolicitud"].replace(tzinfo=UTC),
                "responsable": autores[f["IdSolicitud"]],
                "clase": contenido["clase"],
                "accion": contenido["accion"],
                "datos": contenido.get("datos"),
                "idOrigen": contenido.get("idOrigen"),
            }
        )
    salida = {"fechaConsulta": hoy(), "solicitudes": publicas}
    for clase, valores in conjuntos.items():
        salida[clase] = [
            {
                **{k[0].lower() + k[1:]: v for k, v in fila.items()},
                "responsable": autores.get(fila["IdSolicitud"], "Registro previo"),
                "tipoCanonico": p.particion(fila, clase)
                if clase == "restricciones"
                else None,
            }
            for fila in valores
        ]
    with motor("cooperativa").connect() as catalogo:
        salida["tiposRestriccion"] = [
            dict(f)
            for f in catalogo.execute(
                text(
                    "SELECT Codigo AS codigo,Nombre AS nombre,UsaDias AS usaDias,UsaMonto AS usaMonto,UsaCantidad AS usaCantidad FROM ProductosFinancieros.TipoRestriccion ORDER BY Codigo"
                )
            ).mappings()
        ]
    return salida


@router.get("/subproductos/{id_sub}/vigencias")
@router.get("/subproductos/{id_sub}/condiciones")
def consultar(id_sub: Id, _: Lector, conn: Db, usuario: UsuarioActual) -> dict:
    return leer(id_sub, conn, usuario)


@router.post(
    "/subproductos/{id_sub}/condiciones",
    status_code=202,
    response_model=SolicitudAceptada,
)
def condiciones(
    id_sub: Id,
    datos: CondicionNueva,
    request: Request,
    _: Proponente,
    usuario: UsuarioActual,
    actor: apr.Actual,
    cola: apr.Cola,
):
    return solicitar(
        id_sub,
        Cambio(
            clase="condiciones",
            accion="programar",
            datos=datos.model_dump(mode="json", by_alias=True),
        ),
        request,
        usuario,
        actor,
        cola,
    )


@router.delete(
    "/subproductos/{id_sub}/condiciones/{id_registro}",
    status_code=202,
    response_model=SolicitudAceptada,
)
def cancelar_condicion(
    id_sub: Id,
    id_registro: Id,
    request: Request,
    _: Proponente,
    usuario: UsuarioActual,
    actor: apr.Actual,
    cola: apr.Cola,
):
    return solicitar(
        id_sub,
        Cambio(clase="condiciones", accion="cancelar", id_registro=id_registro),
        request,
        usuario,
        actor,
        cola,
    )


@router.patch("/subproductos/{id_sub}/condiciones/{id_registro}")
@router.patch("/subproductos/{id_sub}/cupos/{id_registro}")
@router.patch("/subproductos/{id_sub}/restricciones/{id_registro}")
def no_editar(id_sub: Id, id_registro: Id, _: Proponente, actor: apr.Actual):
    if "prd-condicion" not in actor.permisos:
        raise problema(403, "SIN_PERMISO", "Falta el permiso efectivo.")
    raise problema(
        409,
        "CONJUNTO_NO_EDITABLE",
        "Los conjuntos registrados no se editan; programe uno nuevo.",
    )


@router.post(
    "/subproductos/{id_sub}/restricciones",
    status_code=202,
    response_model=SolicitudAceptada,
)
def restricciones(
    id_sub: Id,
    datos: RestriccionNueva,
    request: Request,
    _: Proponente,
    usuario: UsuarioActual,
    actor: apr.Actual,
    cola: apr.Cola,
):
    return solicitar(
        id_sub,
        Cambio(
            clase="restricciones",
            accion="programar",
            datos=datos.model_dump(mode="json", by_alias=True),
        ),
        request,
        usuario,
        actor,
        cola,
    )


@router.delete(
    "/subproductos/{id_sub}/restricciones/{id_registro}",
    status_code=202,
    response_model=SolicitudAceptada,
)
def cancelar_restriccion(
    id_sub: Id,
    id_registro: Id,
    request: Request,
    _: Proponente,
    usuario: UsuarioActual,
    actor: apr.Actual,
    cola: apr.Cola,
):
    return solicitar(
        id_sub,
        Cambio(clase="restricciones", accion="cancelar", id_registro=id_registro),
        request,
        usuario,
        actor,
        cola,
    )


@router.post(
    "/subproductos/{id_sub}/restricciones/{id_registro}/fin",
    status_code=202,
    response_model=SolicitudAceptada,
)
def finalizar_restriccion(
    id_sub: Id,
    id_registro: Id,
    datos: FinRestriccion,
    request: Request,
    _: Proponente,
    usuario: UsuarioActual,
    actor: apr.Actual,
    cola: apr.Cola,
):
    return solicitar(
        id_sub,
        Cambio(
            clase="restricciones",
            accion="fin",
            datos=datos.model_dump(mode="json", by_alias=True),
            id_registro=id_registro,
        ),
        request,
        usuario,
        actor,
        cola,
    )


@router.delete(
    "/subproductos/{id_sub}/cupos/programaciones/{id_programacion}",
    status_code=202,
    response_model=SolicitudAceptada,
)
def cancelar_cupos(
    id_sub: Id,
    id_programacion: Id,
    request: Request,
    _: Proponente,
    usuario: UsuarioActual,
    actor: apr.Actual,
    cola: apr.Cola,
):
    return solicitar(
        id_sub,
        Cambio(clase="cupos", accion="cancelar", id_programacion=id_programacion),
        request,
        usuario,
        actor,
        cola,
    )


def cupos(id_sub: int, datos: CuposNuevos, request, usuario, actor, cola):
    return solicitar(
        id_sub,
        Cambio(
            clase="cupos",
            accion="programar",
            datos=datos.model_dump(mode="json", by_alias=True),
        ),
        request,
        usuario,
        actor,
        cola,
    )

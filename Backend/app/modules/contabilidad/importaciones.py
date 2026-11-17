"""Preparación y aplicación transaccional de catálogos del regulador."""

import csv
import io
import json
import re
from collections import Counter
from pathlib import PurePath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import Connection, text
from starlette.concurrency import run_in_threadpool

from app.core.api.errors import ProblemDetailsRoute, problema
from app.core.database.db import cooperativa
from app.core.security.auth import UsuarioActual, require_permiso
from app.core.security.operador import IdInterno, auditar, exigir_id_interno

COLUMNAS = ("CodigoCuenta", "NombreCuenta", "CodigoCuentaSuperior", "Naturaleza")
PADRE = {1: 0, 2: 1, 4: 2, 6: 4}
MAX_BYTES = 2 * 1024 * 1024
MAX_FILAS = 5000

router = APIRouter(
    prefix="/cuentas/importaciones",
    route_class=ProblemDetailsRoute,
    dependencies=[Depends(require_permiso("con-cuenta-editar"))],
)
Db = Annotated[Connection, Depends(cooperativa)]


def archivo_invalido() -> Exception:
    return problema(
        422, "ARCHIVO_INVALIDO", "Use un CSV UTF-8 con las columnas del contrato."
    )


def leer_csv(nombre: str, contenido: bytes) -> list[dict[str, Any]]:
    if (
        len(nombre) > 200
        or PurePath(nombre).suffix.lower() != ".csv"
        or len(contenido) > MAX_BYTES
    ):
        raise archivo_invalido()
    filas: list[dict[str, Any]] = []
    try:
        flujo = io.StringIO(contenido.decode("utf-8-sig"), newline="")
        lector = csv.reader(flujo, strict=True)
        if tuple(next(lector, ())) != COLUMNAS or "\x00" in flujo.getvalue():
            raise archivo_invalido()
        while True:
            numero = lector.line_num + 1
            valores = next(lector, None)
            if valores is None:
                break
            if len(valores) != len(COLUMNAS) or len(filas) == MAX_FILAS:
                raise archivo_invalido()
            filas.append(
                {"numeroFila": numero, **dict(zip(COLUMNAS, map(str.strip, valores)))}
            )
    except (UnicodeError, csv.Error):
        raise archivo_invalido() from None
    if not filas:
        raise archivo_invalido()
    return filas


def revisar(filas: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    codigos = Counter(fila["CodigoCuenta"] for fila in filas)
    validas = set(plan)
    resultados = {}
    for fila in sorted(filas, key=lambda f: len(f["CodigoCuenta"])):
        codigo, nombre, padre, naturaleza = (fila[c] for c in COLUMNAS)
        anterior = plan.get(codigo)
        error = None
        longitud = PADRE.get(len(codigo))
        if longitud is None or not re.fullmatch(r"[0-9]+", codigo):
            error = "CODIGO_INVALIDO"
        elif codigos[codigo] > 1:
            error = "CODIGO_DUPLICADO"
        elif padre != codigo[:longitud] or (padre and padre not in validas):
            error = "CODIGO_NO_CORRESPONDE_AL_PADRE"
        elif (
            not nombre
            or len(nombre) > 150
            or naturaleza not in ("DEUDORA", "ACREEDORA")
        ):
            error = "DATOS_INVALIDOS"
        elif (
            anterior
            and anterior["naturaleza"] != naturaleza
            and (anterior["movimientos"] or anterior["saldo"] or anterior["hijos"])
        ):
            error = "NATURALEZA_EN_USO"
        elif (
            anterior
            and anterior["imputable"]
            and (anterior["movimientos"] or anterior["saldo"])
        ):
            error = "RECLASIFICACION_REQUERIDA"

        resultado = "Error" if error else "Nueva"
        if not error:
            validas.add(codigo)
            if anterior:
                igual = (
                    anterior["nombre"] == nombre
                    and anterior["naturaleza"] == naturaleza
                    and (anterior["padre"] or "") == padre
                    and anterior["regulador"]
                    and not anterior["imputable"]
                )
                resultado = "Igual" if igual else "Cambiada"
        campos = ("nombre", "naturaleza", "padre", "regulador", "imputable")
        resultados[fila["numeroFila"]] = {
            **fila,
            "resultado": resultado,
            "codigoError": error,
            "anterior": {campo: anterior.get(campo) for campo in campos}
            if anterior
            else None,
        }
    return [resultados[fila["numeroFila"]] for fila in filas]


def leer_plan(conn: Connection) -> dict[str, Any]:
    filas = conn.execute(
        text("""
        SELECT c.CodigoCuenta AS codigo, c.NombreCuenta AS nombre, c.Naturaleza AS naturaleza,
               p.CodigoCuenta AS padre, c.EsCatalogoRegulador AS regulador,
               c.EsImputable AS imputable, c.Saldo AS saldo,
               CASE WHEN EXISTS (SELECT 1 FROM Contabilidad.MovimientosContables m WITH (HOLDLOCK)
                                 WHERE m.IdCuentaContable=c.IdCuentaContable) THEN 1 ELSE 0 END AS movimientos,
               CASE WHEN EXISTS (SELECT 1 FROM Contabilidad.CuentasContables h
                                 WHERE h.IdCuentaSuperior=c.IdCuentaContable) THEN 1 ELSE 0 END AS hijos
        FROM Contabilidad.CuentasContables c WITH (UPDLOCK,HOLDLOCK)
        LEFT JOIN Contabilidad.CuentasContables p ON p.IdCuentaContable=c.IdCuentaSuperior
    """)
    ).mappings()
    return {f["codigo"]: f for f in filas}


def obtener(conn: Connection, id_importacion: int, actor: int) -> dict[str, Any]:
    fila = (
        conn.execute(
            text("""
        SELECT IdImportacion, NombreArchivo, Revision, Filas, FilasError, CargadoPor,
               FechaCarga, AplicadoPor, FechaAplicada
        FROM Contabilidad.ImportacionCatalogo WITH (UPDLOCK,HOLDLOCK)
        WHERE IdImportacion=:id AND CargadoPor=:actor
    """),
            {"id": id_importacion, "actor": actor},
        )
        .mappings()
        .one_or_none()
    )
    if fila is None:
        raise problema(404, "IMPORTACION_NO_ENCONTRADA", "No existe la importación.")
    datos = dict(fila)
    datos["revision"] = json.loads(datos.pop("Revision"))
    datos["estado"] = "Aplicada" if datos["AplicadoPor"] is not None else "Revision"
    return datos


@router.post("", status_code=201)
async def subir(
    conn: Db,
    id_interno: IdInterno,
    request: Request,
    nombre: Annotated[str, Header(alias="X-Nombre-Archivo")] = "",
) -> dict[str, Any]:
    actor = exigir_id_interno(id_interno)
    if (
        request.headers.get("content-type", "").split(";")[0].strip().lower()
        != "text/csv"
    ):
        raise archivo_invalido()
    contenido = bytearray()
    async for fragmento in request.stream():
        if len(contenido) + len(fragmento) > MAX_BYTES:
            raise archivo_invalido()
        contenido.extend(fragmento)
    filas = leer_csv(nombre, bytes(contenido))
    return await run_in_threadpool(guardar_revision, conn, actor, nombre, filas)


def guardar_revision(
    conn: Connection, actor: int, nombre: str, filas: list[dict[str, Any]]
) -> dict[str, Any]:
    with conn.begin():
        revision = revisar(filas, leer_plan(conn))
        id_importacion = conn.execute(
            text("""
            INSERT Contabilidad.ImportacionCatalogo (NombreArchivo,Revision,Filas,FilasError,CargadoPor)
            OUTPUT inserted.IdImportacion VALUES (:nombre,:revision,:filas,:errores,:actor)
        """),
            {
                "nombre": nombre,
                "revision": json.dumps(revision),
                "filas": len(filas),
                "errores": sum(f["resultado"] == "Error" for f in revision),
                "actor": actor,
            },
        ).scalar_one()
        return obtener(conn, id_importacion, actor)


@router.get("/{id_importacion}")
def detalle(conn: Db, id_importacion: int, id_interno: IdInterno) -> dict[str, Any]:
    return obtener(conn, id_importacion, exigir_id_interno(id_interno))


@router.post("/{id_importacion}/aplicar")
def aplicar_ruta(
    conn: Db,
    id_importacion: int,
    id_interno: IdInterno,
    usuario: UsuarioActual,
    request: Request,
) -> dict[str, Any]:
    actor = exigir_id_interno(id_interno)
    with auditar(
        "CON_CATALOGO_IMPORTADO",
        "Contabilidad.ImportacionCatalogo",
        usuario,
        request.client.host if request.client else "",
        "",
        str(id_importacion),
    ):
        return aplicar(conn, id_importacion, actor)


def aplicar(conn: Connection, id_importacion: int, actor: int) -> dict[str, Any]:
    with conn.begin():
        datos = obtener(conn, id_importacion, actor)
        if datos["AplicadoPor"] is not None:
            return datos
        if datos["FilasError"]:
            raise problema(
                422,
                "IMPORTACION_CON_ERRORES",
                "Corrija el archivo y vuelva a cargarlo.",
            )
        revision = datos["revision"]
        if revisar(revision, leer_plan(conn)) != revision:
            raise problema(
                409,
                "CATALOGO_CAMBIO",
                "Cargue el archivo de nuevo para revisar el catálogo actual.",
            )
        for fila in sorted(revision, key=lambda f: len(f["CodigoCuenta"])):
            if fila["resultado"] == "Igual":
                continue
            conn.execute(
                text("""
                DECLARE @padre int = (SELECT IdCuentaContable FROM Contabilidad.CuentasContables
                                      WHERE CodigoCuenta=:CodigoCuentaSuperior);
                IF :resultado='Nueva'
                    INSERT Contabilidad.CuentasContables
                        (CodigoCuenta,NombreCuenta,IdCuentaSuperior,Naturaleza,EsImputable,
                         Estado,EsCatalogoRegulador,CreadoPor)
                    VALUES (:CodigoCuenta,:NombreCuenta,@padre,:Naturaleza,0,1,1,:actor);
                ELSE
                    UPDATE Contabilidad.CuentasContables SET NombreCuenta=:NombreCuenta,
                        IdCuentaSuperior=@padre,Naturaleza=:Naturaleza,EsImputable=0,
                        EsCatalogoRegulador=1,ModificadoPor=:actor,FechaModificacion=SYSDATETIME()
                    WHERE CodigoCuenta=:CodigoCuenta;
            """),
                {**fila, "actor": actor},
            )
        conn.execute(
            text("""
            UPDATE Contabilidad.ImportacionCatalogo SET AplicadoPor=:actor,FechaAplicada=SYSUTCDATETIME()
            WHERE IdImportacion=:id
        """),
            {"actor": actor, "id": id_importacion},
        )
        return obtener(conn, id_importacion, actor)

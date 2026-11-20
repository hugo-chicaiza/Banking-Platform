"""Verifica la importación en una copia local posterior al corte E2-01."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pyodbc
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from app.core.database.db import cooperativa
from app.modules.contabilidad import importaciones
from app.modules.contabilidad.importaciones import (
    aplicar,
    guardar_revision,
    leer_csv,
    obtener,
)
from app.modules.contabilidad.schemas import CuentaContableEditar
from app.modules.contabilidad.service import editar_cuenta_contable
from tests.sesion import simular_sesion, usuario_con_roles

CABECERA = b"CodigoCuenta,NombreCuenta,CodigoCuentaSuperior,Naturaleza\n"


def verificar_concurrencia(engine: Engine, id_importacion: int):
    barrera = Barrier(2, timeout=10)

    def aplicar_en_conexion():
        with engine.connect() as conn:
            barrera.wait()
            return aplicar(conn, id_importacion, 101)

    with ThreadPoolExecutor(max_workers=2) as executor:
        primera = executor.submit(aplicar_en_conexion)
        segunda = executor.submit(aplicar_en_conexion)
        resultado = primera.result(timeout=30)
        assert resultado == segunda.result(timeout=30)
        return resultado


def verificar_endpoints(engine: Engine) -> None:
    app = FastAPI()
    app.include_router(importaciones.router, prefix="/api/v1/contabilidad")

    def conexion():
        with engine.connect() as conn:
            yield conn

    app.dependency_overrides[cooperativa] = conexion
    ruta = "/api/v1/contabilidad/cuentas/importaciones"
    headers = {"Content-Type": "text/csv", "X-Nombre-Archivo": "cuc.csv"}
    contenido = CABECERA + "110197,Revisión de año,1101,DEUDORA\n".encode()
    with (
        patch(
            "app.modules.seguridad.funciones.autorizar_operacion", return_value=False
        ),
        patch("app.core.security.operador.audit.registrar") as auditoria,
        TestClient(app) as cliente,
    ):
        simular_sesion(app, usuario_con_roles("CONTADOR"))
        invalida = cliente.post(ruta, headers=headers, content=b"mal\xff")
        assert invalida.status_code == 422
        assert invalida.json()["code"] == "ARCHIVO_INVALIDO"
        incompatible = cliente.post(
            ruta,
            headers=headers,
            content=CABECERA + "110197,Cuenta 漢,1101,DEUDORA\n".encode(),
        )
        assert incompatible.status_code == 201
        revision_incompatible = incompatible.json()
        assert revision_incompatible["FilasError"] == 1
        fila = revision_incompatible["revision"][0]
        assert fila["numeroFila"] == 2 and fila["codigoError"] == "DATOS_INVALIDOS"
        bloqueada = cliente.post(
            f"{ruta}/{revision_incompatible['IdImportacion']}/aplicar"
        )
        assert bloqueada.status_code == 422
        assert bloqueada.json()["code"] == "IMPORTACION_CON_ERRORES"
        carga = cliente.post(ruta, headers=headers, content=contenido)
        assert carga.status_code == 201
        revision = carga.json()
        detalle = f"{ruta}/{revision['IdImportacion']}"
        assert cliente.get(detalle).json() == revision
        aplicar_url = f"{detalle}/aplicar"
        aplicada = cliente.post(aplicar_url)
        assert aplicada.status_code == 200
        assert aplicada.json()["estado"] == "Aplicada"
        assert aplicada.json()["AplicadoPor"] == 1
        assert aplicada.json()["FechaAplicada"]
        evento = auditoria.call_args.args[0]
        assert evento.accion == "CON_CATALOGO_IMPORTADO"
        assert evento.id_registro == str(revision["IdImportacion"])
        assert (
            evento.resultado == "Exitoso"
            and "usuario=user_prueba " in evento.descripcion
        )
        assert cliente.get(detalle).json() == aplicada.json()
        assert cliente.post(aplicar_url).json() == aplicada.json()
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT NombreCuenta FROM Contabilidad.CuentasContables WHERE CodigoCuenta='110197'"
                    )
                ).scalar_one()
                == "Revisión de año"
            )
        with patch.object(
            importaciones,
            "obtener",
            side_effect=DBAPIError(
                "SELECT dato_interno",
                {"nombre": "VALOR_PRIVADO_QA"},
                RuntimeError("MENSAJE_INTERNO_QA"),
            ),
        ):
            fallo = cliente.get(detalle)
        assert fallo.status_code == 500
        assert fallo.json()["code"] == "ERROR_INTERNO" and fallo.json()["traceId"]
        for dato in ("dato_interno", "VALOR_PRIVADO_QA", "MENSAJE_INTERNO_QA"):
            assert dato not in fallo.text
        for metodo, url in (
            ("GET", f"{ruta}/{2**63}"),
            ("POST", f"{ruta}/{2**63}/aplicar"),
        ):
            respuesta = cliente.request(metodo, url)
            assert respuesta.status_code == 400, respuesta.json()
            assert respuesta.json()["code"] == "DATOS_INVALIDOS"
        simular_sesion(
            app,
            replace(
                usuario_con_roles("CONTADOR"), id_interno=102, id_usuario="user_otro"
            ),
        )
        for metodo, url in (("GET", detalle), ("POST", aplicar_url)):
            respuesta = cliente.request(metodo, url)
            assert respuesta.status_code == 404
            assert respuesta.json()["code"] == "IMPORTACION_NO_ENCONTRADA"
        simular_sesion(app, usuario_con_roles("ASESOR"))
        assert cliente.post(ruta, headers=headers, content=contenido).status_code == 403
        assert cliente.get(detalle).status_code == 403
        assert cliente.post(aplicar_url).status_code == 403


def probar(database: str) -> None:
    if not database.startswith("CooperativaDB_E201_Lab_"):
        raise ValueError("Se requiere una base local E2-01 de ensayo.")
    servidor = os.environ["COMPUTERNAME"]
    cadena = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={servidor};DATABASE={database};"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
    )

    def conectar():
        db = pyodbc.connect(cadena)
        identidad = db.execute("SELECT DB_NAME(), @@SERVERNAME").fetchone()
        assert identidad is not None
        base, instancia = identidad
        assert base.casefold() == database.casefold()
        assert instancia.casefold() == servidor.casefold()
        db.rollback()
        return db

    migracion = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "20261117_e203_importacion.sql"
    )
    with conectar() as db:
        sql = migracion.read_text(encoding="utf-8-sig")
        db.execute(sql)
        db.execute(sql)
    engine = create_engine("mssql+pyodbc://", creator=conectar)
    with engine.connect() as conn:
        invalida = guardar_revision(
            conn,
            101,
            "cuc.csv",
            leer_csv("cuc.csv", CABECERA + b"999999,Sin padre,9999,DEUDORA\n"),
        )
        assert invalida["revision"][0]["numeroFila"] == 2
        assert (
            invalida["revision"][0]["codigoError"] == "CODIGO_NO_CORRESPONDE_AL_PADRE"
        )
        try:
            aplicar(conn, invalida["IdImportacion"], 101)
        except HTTPException as error:
            assert error.status_code == 422
            assert isinstance(error.detail, dict)
            assert error.detail.get("code") == "IMPORTACION_CON_ERRORES"
        else:
            raise AssertionError("Se aplicó una revisión con errores.")

        anterior = conn.execute(
            text("""
            SELECT NombreCuenta FROM Contabilidad.CuentasContables WHERE CodigoCuenta='110197'
        """)
        ).scalar_one_or_none()
        conn.rollback()
        nombre = (
            "Importacion E203 B"
            if anterior == "Importacion E203 A"
            else "Importacion E203 A"
        )
        filas = leer_csv(
            "cuc.csv", CABECERA + f"110197,{nombre},1101,DEUDORA\n".encode()
        )
        revision = guardar_revision(conn, 101, "cuc.csv", filas)
        assert revision["revision"][0]["resultado"] == (
            "Nueva" if anterior is None else "Cambiada"
        )

        def fallar_confirmacion(_conn, _cursor, sentencia, *_args):
            if "SET AplicadoPor=" in sentencia:
                raise RuntimeError("Fallo de confirmación simulado")

        event.listen(conn, "before_cursor_execute", fallar_confirmacion)
        try:
            aplicar(conn, revision["IdImportacion"], 101)
        except RuntimeError as error:
            assert str(error) == "Fallo de confirmación simulado"
        else:
            raise AssertionError("No se provocó el fallo de confirmación.")
        finally:
            event.remove(conn, "before_cursor_execute", fallar_confirmacion)
        with conn.begin():
            assert obtener(conn, revision["IdImportacion"], 101) == revision
            assert (
                conn.execute(
                    text(
                        "SELECT NombreCuenta FROM Contabilidad.CuentasContables WHERE CodigoCuenta='110197'"
                    )
                ).scalar_one_or_none()
                == anterior
            )

        aplicado = verificar_concurrencia(engine, revision["IdImportacion"])
        assert aplicado["AplicadoPor"] == 101 and aplicado["FechaAplicada"]
        assert aplicado["FilasNuevas"] == int(anterior is None)
        assert aplicado["FilasCambiadas"] == int(anterior is not None)
        assert aplicado["FilasIguales"] == 0
        assert aplicar(conn, revision["IdImportacion"], 101) == aplicado
        sin_cambios = guardar_revision(conn, 101, "cuc.csv", filas)
        assert aplicar(conn, sin_cambios["IdImportacion"], 101)["FilasIguales"] == 1
        filas = leer_csv(
            "cuc.csv", CABECERA + b"110197,Revision anterior,1101,DEUDORA\n"
        )
        revision = guardar_revision(conn, 101, "cuc.csv", filas)
        with conn.begin():
            conn.execute(
                text("""
                UPDATE Contabilidad.CuentasContables SET NombreCuenta='Cambio concurrente'
                WHERE CodigoCuenta='110197'
            """)
            )
        try:
            aplicar(conn, revision["IdImportacion"], 101)
        except HTTPException as error:
            assert isinstance(error.detail, dict)
            assert (
                error.status_code == 409
                and error.detail.get("code") == "CATALOGO_CAMBIO"
            )
        else:
            raise AssertionError("La importación sobrescribió el cambio concurrente.")
        with conn.begin():
            conn.execute(
                text("""
                IF NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables WHERE CodigoCuenta='11019701')
                    INSERT Contabilidad.CuentasContables
                        (CodigoCuenta,NombreCuenta,IdCuentaSuperior,Naturaleza,EsImputable,
                         Estado,EsCatalogoRegulador,CreadoPor)
                    SELECT '11019701','Auxiliar del ensayo',IdCuentaContable,'DEUDORA',1,1,0,101
                    FROM Contabilidad.CuentasContables WHERE CodigoCuenta='110197'
            """)
            )
        ids = {
            str(fila["CodigoCuenta"]): int(fila["IdCuentaContable"])
            for fila in conn.execute(
                text("""
                    SELECT CodigoCuenta,IdCuentaContable
                    FROM Contabilidad.CuentasContables
                    WHERE CodigoCuenta IN ('11019701','110197')
                """)
            ).mappings()
        }
        conn.rollback()
        datos = CuentaContableEditar(nombre_cuenta="Efectivo en bóveda del ensayo")
        renombrada = editar_cuenta_contable(conn, ids["11019701"], datos, 101)
        assert renombrada["nombre_cuenta"] == datos.nombre_cuenta
        try:
            editar_cuenta_contable(conn, ids["110197"], datos, 101)
        except HTTPException as error:
            assert isinstance(error.detail, dict)
            assert (
                error.status_code == 409
                and error.detail.get("code") == "CUENTA_DEL_REGULADOR"
            )
        else:
            raise AssertionError("Se permitió modificar el CUC por mantenimiento.")
    verificar_endpoints(engine)
    engine.dispose()
    print("Endpoints, permisos, rollback, concurrencia y compatibilidad E2-02: OK")


if __name__ == "__main__":
    probar(sys.argv[1])

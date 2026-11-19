"""Opt-in: SQL LocalDB exclusivo; jamás acepta una conexión Azure o datos de negocio."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database.db import cooperativa, get_engine
from app.main import app
from app.modules.clientes import service as clientes_service
from app.modules.seguridad import funciones, funciones_repository
from app.modules.seguridad.funciones_schemas import CambiosFunciones
from tests.sesion import simular_sesion, usuario_con_roles

pytestmark = pytest.mark.skipif(
    os.environ.get("ENQUO_FUNCIONES_SQL_LAB") != "1",
    reason="Requiere laboratorio LocalDB explícito y transporte SQL local verificado.",
)


@pytest.fixture
def sql_local():
    engine = get_engine("seguridad")
    conexion = str(engine.url.query.get("odbc_connect", "")).lower()
    assert "server=(localdb)\\enquoaccesosqa;" in conexion
    assert "database=seguridaddb;" in conexion
    assert "database.windows.net" not in conexion
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT CONVERT(int,SERVERPROPERTY('IsLocalDB'))")
            ).scalar_one()
            == 1
        )
        assert (
            conn.execute(
                text(
                    "SELECT CONVERT(nvarchar(100),value) FROM sys.extended_properties WHERE name='EnquoLab' AND class=0"
                )
            ).scalar_one()
            == "accesos-474"
        )
        assert conn.execute(text("SELECT DB_NAME()")).scalar_one() == "SeguridadDB"
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM Organizacion.Usuarios WHERE UsuarioID=1")
            ).scalar_one()
            == 1
        )
        antes = funciones_repository.leer(conn)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM Seguridad.AccesoFuncionRol"))
    try:
        yield engine
    finally:
        app.dependency_overrides.clear()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM Seguridad.AccesoFuncionRol"))
            for (id_, rol), valor in antes.items():
                funciones_repository.escribir(conn, id_, rol, valor, 1)


def consultar(engine):
    with engine.connect() as conn:
        return funciones.configuracion(conn)


def datos(
    engine, cambios, version=None, motivo="QA funciones: cambio autorizado local"
):
    return CambiosFunciones.model_validate(
        {
            "version": version or consultar(engine).version,
            "motivo": motivo,
            "cambios": cambios,
        }
    )


def guardar(engine, config):
    with engine.connect() as conn:
        return funciones.guardar(
            conn, config, usuario_con_roles("ADMIN"), 1, "127.0.0.1"
        )


CONCEDER = {"funcion": "clientes.registrar", "rol": "SUPERVISOR", "permitido": True}


def test_persistencia_auditoria_y_restauracion(sql_local):
    engine = sql_local
    resultado = guardar(engine, datos(engine, [CONCEDER]))
    assert resultado.cambios_aplicados == 1
    assert consultar(engine).ajustes[0].permitido is True
    with engine.connect() as conn:
        fila = conn.execute(
            text(
                "SELECT TOP 1 UsuarioID,Descripcion,Resultado,IDRegistro FROM Auditoria.Auditoria WHERE NombreAccion='CONFIGURAR_FUNCION' ORDER BY AuditoriaID DESC"
            )
        ).one()
        assert fila[0] == 1 and fila[2] == "Exitoso" and len(fila[3]) == 64
        assert "clientes.registrar" in fila[1] and "SUPERVISOR" in fila[1]
        assert "QA funciones" in fila[1]
    # Una solicitud idéntica no escribe ni añade una falsa modificación.
    assert guardar(engine, datos(engine, [CONCEDER])).cambios_aplicados == 0
    restaurar = {**CONCEDER, "permitido": None}
    assert guardar(engine, datos(engine, [restaurar])).cambios_aplicados == 1
    assert consultar(engine).ajustes == []


def test_patch_no_reemplaza_ajustes_ajenos_y_rechaza_version_vieja(sql_local):
    engine = sql_local
    version = consultar(engine).version
    guardar(engine, datos(engine, [CONCEDER], version))
    with pytest.raises(HTTPException) as exc:
        guardar(
            engine,
            datos(
                engine,
                [
                    {
                        "funcion": "clientes.consultar",
                        "rol": "CAJERO",
                        "permitido": False,
                    }
                ],
                version,
            ),
        )
    assert exc.value.status_code == 409
    guardar(
        engine,
        datos(
            engine,
            [{"funcion": "clientes.registrar", "rol": "CAJERO", "permitido": True}],
        ),
    )
    assert len(consultar(engine).ajustes) == 2


def test_bloqueo_concurrente_y_dos_escritores(sql_local):
    engine = sql_local
    version = consultar(engine).version
    with engine.begin() as conn:
        conn.execute(
            text(
                "DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource='enquo-funciones',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=0; SELECT @r"
            )
        ).scalar_one()
        with pytest.raises(HTTPException) as exc:
            guardar(engine, datos(engine, [CONCEDER], version))
        assert exc.value.status_code == 409
    barrera = Barrier(2)

    def escritor(rol):
        barrera.wait()
        try:
            guardar(engine, datos(engine, [{**CONCEDER, "rol": rol}], version))
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(2) as pool:
        futuros = [pool.submit(escritor, r) for r in ("SUPERVISOR", "CAJERO")]
        assert sorted(f.result() for f in futuros) == [200, 409]
    assert len(consultar(engine).ajustes) == 1


def test_fallo_auditoria_revierte_todo_y_motivo_maximo(sql_local):
    engine = sql_local
    version = consultar(engine).version
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE OR ALTER TRIGGER Auditoria.QA_FalloFunciones ON Auditoria.Auditoria AFTER INSERT AS BEGIN IF EXISTS(SELECT 1 FROM inserted WHERE NombreAccion='CONFIGURAR_FUNCION' AND Descripcion LIKE '%QA fallo funciones%') THROW 51002, 'Fallo deliberado solo local', 1; END"
            )
        )
    try:
        with pytest.raises(HTTPException) as exc:
            guardar(
                engine, datos(engine, [CONCEDER], motivo="QA fallo funciones auditoria")
            )
        assert exc.value.status_code == 503
        assert consultar(engine).version == version
        assert consultar(engine).ajustes == []
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TRIGGER Auditoria.QA_FalloFunciones"))
    guardar(engine, datos(engine, [CONCEDER], motivo='"' * 160))
    with engine.connect() as conn:
        descripcion = conn.execute(
            text(
                "SELECT TOP 1 Descripcion FROM Auditoria.Auditoria WHERE NombreAccion='CONFIGURAR_FUNCION' ORDER BY AuditoriaID DESC"
            )
        ).scalar_one()
        assert descripcion.endswith('"' * 160)


def test_migracion_reejecutable_y_restricciones(sql_local):
    engine = sql_local
    sql = (
        Path(__file__).resolve().parents[2]
        / "migrations/20261118_seguridad_acceso_funcion_rol.tsql"
    ).read_text(encoding="utf-8-sig")
    import re

    with engine.begin() as conn:
        for lote in re.split(r"^GO\s*$", sql, flags=re.MULTILINE | re.IGNORECASE):
            if lote.strip():
                conn.exec_driver_sql(lote)
        assert (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM sys.foreign_keys WHERE parent_object_id=OBJECT_ID('Seguridad.AccesoFuncionRol') AND is_disabled=0"
                )
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize(
    "funcion,rol,actor",
    [
        ("clientes.registrar", "INVENTADO", 1),
        ("funcion/con/barra", "SUPERVISOR", 1),
        ("clientes.registrar", "SUPERVISOR", 2147483647),
    ],
)
def test_restricciones_reales_rechazan_filas_invalidas(sql_local, funcion, rol, actor):
    with pytest.raises(DBAPIError), sql_local.begin() as conn:
        funciones_repository.escribir(conn, funcion, rol, True, actor)


def test_reversion_no_borra_ajustes_y_conserva_auditoria(sql_local):
    import re

    engine = sql_local
    guardar(engine, datos(engine, [CONCEDER]))
    directorio = Path(__file__).resolve().parents[2] / "migrations"
    down = (directorio / "20261118_seguridad_acceso_funcion_rol.down.tsql").read_text(
        encoding="utf-8-sig"
    )
    up = (directorio / "20261118_seguridad_acceso_funcion_rol.tsql").read_text(
        encoding="utf-8-sig"
    )
    with pytest.raises(DBAPIError), engine.begin() as conn:
        for lote in re.split(r"^GO\s*$", down, flags=re.MULTILINE | re.IGNORECASE):
            if lote.strip():
                conn.exec_driver_sql(lote)
    guardar(engine, datos(engine, [{**CONCEDER, "permitido": None}]))
    with engine.begin() as conn:
        conteo = conn.execute(
            text(
                "SELECT COUNT(*) FROM Auditoria.Auditoria WHERE NombreAccion='CONFIGURAR_FUNCION'"
            )
        ).scalar_one()
        for script in (down, up):
            for lote in re.split(
                r"^GO\s*$", script, flags=re.MULTILINE | re.IGNORECASE
            ):
                if lote.strip():
                    conn.exec_driver_sql(lote)
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM Seguridad.AccesoFuncionRol")
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM Auditoria.Auditoria WHERE NombreAccion='CONFIGURAR_FUNCION'"
                )
            ).scalar_one()
            == conteo
        )


def test_no_ignora_personalizaciones_antiguas_al_activar(sql_local):
    engine = sql_local
    with engine.begin() as conn:
        assert (
            conn.execute(text("SELECT COUNT(*) FROM Seguridad.PestanaRol")).scalar_one()
            == 0
        )
        conn.execute(
            text(
                "INSERT Seguridad.PestanaRol(Pestana,Roles,ModificadoPor) VALUES ('/clientes-busqueda','ADMIN',1)"
            )
        )
        try:
            with pytest.raises(HTTPException) as exc:
                funciones.configuracion(conn)
            assert exc.value.status_code == 503
        finally:
            conn.execute(
                text(
                    "DELETE FROM Seguridad.PestanaRol WHERE Pestana='/clientes-busqueda' AND ModificadoPor=1"
                )
            )


def test_api_editor_y_registro_real_del_router_con_politica_sql(sql_local, monkeypatch):
    engine = sql_local
    # Solo se simulan la identidad y el guardado del cliente; política, configuración,
    # transacción y auditoría del editor utilizan SQL real local.
    simular_sesion(app, usuario_con_roles("ADMIN"))
    app.dependency_overrides[cooperativa] = lambda: object()
    llamadas = []

    def registrar(*args):
        llamadas.append(True)
        return JSONResponse({"clienteFicticio": True}, status_code=201)

    monkeypatch.setattr(clientes_service, "registrar_cliente", registrar)
    payload = {
        "identificacion": "A12345678",
        "tipoDocumento": "P",
        "tipoCliente": "Natural",
        "nombres": "Persona QA",
        "apellidos": "Local",
        "idActividadEconomica": 1,
        "fechaNacimiento": "1990-05-14",
        "genero": "F",
        "estadoCivil": "Soltero",
        "codigoPaisNacionalidad": "ECU",
        "telefonoCelular": "0991234567",
        "email": "qa@example.ec",
        "consentimientoDatos": True,
        "direccion": {
            "tipoDireccion": "Domicilio",
            "codigoPais": "ECU",
            "idCiudad": 1,
            "calleDireccion": "Calle de laboratorio",
            "referenciaUbicacion": "Solo para prueba local",
            "esPrincipal": True,
        },
    }
    with TestClient(app, base_url="https://testserver") as cliente:
        config = cliente.get("/api/v1/seguridad/accesos/configuracion")
        assert config.status_code == 200
        assert config.headers["cache-control"] == "no-store"
        conceder = cliente.patch(
            "/api/v1/seguridad/accesos/configuracion",
            json={
                "version": config.json()["version"],
                "motivo": "QA funciones: concesion desde API",
                "cambios": [CONCEDER],
            },
        )
        assert conceder.status_code == 200, conceder.text
        simular_sesion(app, usuario_con_roles("SUPERVISOR"))
        alta = cliente.post("/api/v1/clientes", json=payload)
        assert alta.status_code == 201, alta.text
        simular_sesion(app, usuario_con_roles("ADMIN"))
        retirar = cliente.patch(
            "/api/v1/seguridad/accesos/configuracion",
            json={
                "version": consultar(engine).version,
                "motivo": "QA funciones: retirada desde API",
                "cambios": [{**CONCEDER, "permitido": False}],
            },
        )
        assert retirar.status_code == 200
        simular_sesion(app, usuario_con_roles("SUPERVISOR"))
        assert cliente.post("/api/v1/clientes", json=payload).status_code == 403
    assert len(llamadas) == 1

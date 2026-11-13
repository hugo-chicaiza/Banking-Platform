r"""Entidad contra SQL Server local, en una base temporal exclusiva de estas pruebas.

Activar con ENTIDAD_LOCAL_SQL_ENABLED=1. Instancia predeterminada .\SQLEXPRESS,
configurable con ENTIDAD_LOCAL_SQL_SERVER, exclusivamente en el equipo local.
La fixture crea y elimina su propia base con un nombre generado por UUID.
"""

import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from uuid import uuid4

import pyodbc
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.core.database.db import cooperativa
from app.modules.organizacion import repository, service
from app.modules.organizacion.router import router
from app.modules.organizacion.schemas import EntidadCreate, EntidadUpdate
from tests.sesion import simular_sesion, usuario_con_roles

pytestmark = pytest.mark.skipif(
    os.environ.get("ENTIDAD_LOCAL_SQL_ENABLED") != "1",
    reason="Requiere ENTIDAD_LOCAL_SQL_ENABLED=1 y SQL Server local",
)
RUTA = "/api/v1/organizacion/entidad"
DATOS_CREACION = {
    "ruc": "1790000000001",
    "razonSocial": "Entidad SQL de prueba",
    "fechaConstitucion": "2000-01-01",
    "representanteLegal": "Representante SQL",
    "identificacionRepresentante": "AB12345",
}

# DDL de la tabla compartido para esta funcionalidad. Los índices usan las
# opciones predeterminadas de SQL Server, conservando PK, UNIQUE y CHECK.
DDL_ENTIDAD = """
CREATE TABLE Organizacion.Entidad (
    IdEntidad tinyint NOT NULL CONSTRAINT PK_Entidad PRIMARY KEY,
    RUC char(13) NOT NULL CONSTRAINT UQ_Entidad_RUC UNIQUE,
    RazonSocial varchar(250) NOT NULL,
    NombreComercial varchar(150) NULL,
    TipoOrganizacion varchar(60) NOT NULL
        CONSTRAINT DF_Entidad_TipoOrganizacion DEFAULT ('Cooperativa de Ahorro y Credito'),
    Segmento tinyint NULL,
    NumeroResolucionSEPS varchar(60) NULL,
    FechaConstitucion date NOT NULL,
    RepresentanteLegal varchar(250) NOT NULL,
    IdentificacionRepresentante varchar(13) NOT NULL,
    Telefono varchar(15) NULL,
    Email varchar(150) NULL,
    SitioWeb varchar(150) NULL,
    Estado char(1) NOT NULL CONSTRAINT DF_Entidad_Estado DEFAULT ('A'),
    FechaRegistro datetime2(7) NOT NULL CONSTRAINT DF_Entidad_FechaRegistro
        DEFAULT (CONVERT(datetime2, (sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time'))),
    ModificadoPor int NOT NULL,
    CONSTRAINT CK_Entidad_Estado CHECK (Estado IN ('A', 'I')),
    CONSTRAINT CK_Entidad_Representante CHECK (
        IdentificacionRepresentante NOT LIKE '%[^0-9A-Z]%'
        AND LEN(IdentificacionRepresentante) BETWEEN 5 AND 13),
    CONSTRAINT CK_Entidad_RUC CHECK (RUC NOT LIKE '%[^0-9]%' AND RIGHT(RUC, 3) = '001'),
    CONSTRAINT CK_Entidad_Segmento CHECK (Segmento IS NULL OR Segmento BETWEEN 1 AND 5),
    CONSTRAINT CK_Entidad_UnaFila CHECK (IdEntidad = 1)
)
"""


@pytest.fixture(scope="module")
def engine():
    servidor = os.environ.get("ENTIDAD_LOCAL_SQL_SERVER", r".\SQLEXPRESS")
    patron_local = (
        r"(?:\.|\(local\)|localhost|"
        + re.escape(socket.gethostname())
        + r")(?:\\[A-Za-z0-9_]+)?"
    )
    if not re.fullmatch(patron_local, servidor, flags=re.IGNORECASE):
        pytest.fail("ENTIDAD_LOCAL_SQL_SERVER debe identificar el equipo local")
    base = "Entidad_Test_" + uuid4().hex

    def conectar(database):
        return pyodbc.connect(
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={servidor};DATABASE={database};Trusted_Connection=yes;"
            "Encrypt=no;APP=Entidad_SQL_Lab;",
            autocommit=True,
            timeout=5,
        )

    master = conectar("master")
    # El identificador contiene únicamente el prefijo fijo y el UUID generado.
    master.execute(f"CREATE DATABASE [{base}]")

    def conexion_lab():
        raw = conectar(base)
        raw.autocommit = False
        if raw.execute("SELECT DB_NAME()").fetchval() != base:
            raw.close()
            raise RuntimeError("La conexión debe apuntar a la base temporal de entidad")
        raw.rollback()
        return raw

    motor = create_engine("mssql+pyodbc://", creator=conexion_lab, poolclass=NullPool)
    try:
        with motor.begin() as conn:
            conn.exec_driver_sql("CREATE SCHEMA Organizacion")
            conn.exec_driver_sql(DDL_ENTIDAD)
        yield motor
    finally:
        motor.dispose()
        try:
            # Cierra también sesiones retenidas por el pooling nativo de ODBC.
            master.execute(
                f"ALTER DATABASE [{base}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE"
            )
            master.execute(f"DROP DATABASE [{base}]")
        finally:
            master.close()


@pytest.fixture
def sql_app(engine):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM Organizacion.Entidad"))
        conn.execute(
            text("""
                INSERT INTO Organizacion.Entidad
                    (IdEntidad, RUC, RazonSocial, NombreComercial, Segmento,
                     NumeroResolucionSEPS, FechaConstitucion, RepresentanteLegal,
                     IdentificacionRepresentante, Telefono, Email, SitioWeb,
                     FechaRegistro, ModificadoPor)
                VALUES (1, '1790000000001', 'Entidad SQL de prueba', 'Nombre SQL', 2,
                        'SEPS-LAB', '20000101', 'Representante SQL', 'AB12345',
                        '022345678', 'entidad@example.com', 'https://example.com',
                        '20261111 20:15:41', 9)
            """)
        )

    def conexion():
        with engine.connect() as conn:
            yield conn

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[cooperativa] = conexion
    simular_sesion(app, usuario_con_roles("ADMIN"))
    with TestClient(app) as cliente:
        yield app, cliente


@pytest.fixture
def entidad_vacia(engine, sql_app):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM Organizacion.Entidad"))
    return sql_app


@pytest.mark.parametrize("rol", ["ASESOR", "ADMIN"])
def test_get_http_sobre_sql(engine, sql_app, rol):
    app, cliente = sql_app
    simular_sesion(app, usuario_con_roles(rol))
    r = cliente.get(RUTA)
    assert r.status_code == 200, r.text
    assert r.json()["idEntidad"] == 1
    assert r.json()["ruc"] == "1790000000001"
    assert r.json()["estado"] == "A"
    assert r.json()["tipoOrganizacion"] == "Cooperativa de Ahorro y Credito"


def test_patch_http_persiste_todos_los_campos(engine, sql_app, eventos_auditados):
    _, cliente = sql_app
    datos = {
        "ruc": "0990000000001",
        "razonSocial": "Nueva entidad SQL",
        "nombreComercial": "Nuevo nombre SQL",
        "tipoOrganizacion": "Otra organización",
        "segmento": 5,
        "numeroResolucionSeps": "SEPS-NUEVA",
        "fechaConstitucion": "1999-12-31",
        "representanteLegal": "Nuevo representante",
        "identificacionRepresentante": "ABC1234567890",
        "telefono": "0999999999",
        "email": "nueva@example.org",
        "sitioWeb": "https://example.org",
        "estado": "I",
    }
    r = cliente.patch(RUTA, json=datos)
    assert r.status_code == 200, r.text
    with engine.connect() as conn:
        persistido = service.obtener_entidad(conn).model_dump(
            mode="json", by_alias=True
        )
    assert r.json() == persistido
    assert {campo: persistido[campo] for campo in datos} == datos
    assert persistido["modificadoPor"] == 1
    assert persistido["fechaRegistro"] == "2026-11-11T20:15:41"
    assert len(eventos_auditados) == 1


@pytest.mark.parametrize(
    "campo",
    [
        "nombreComercial",
        "segmento",
        "numeroResolucionSeps",
        "telefono",
        "email",
        "sitioWeb",
    ],
)
def test_patch_sql_distingue_null_de_omitido(engine, sql_app, campo):
    _, cliente = sql_app
    antes = cliente.get(RUTA).json()
    r = cliente.patch(RUTA, json={campo: None})
    assert r.status_code == 200, r.text
    esperado = antes | {campo: None, "modificadoPor": 1}
    assert r.json() == esperado
    assert cliente.get(RUTA).json() == esperado


@pytest.mark.parametrize("nocount", ["ON", "OFF"])
def test_servicio_funciona_con_ambas_opciones_nocount(engine, sql_app, nocount):
    with engine.connect() as conn:
        conn.exec_driver_sql("SET NOCOUNT " + nocount)
        conn.commit()
        resultado, campos = service.editar_entidad(
            conn, EntidadUpdate(telefono="0991111111"), 47
        )
        assert resultado.telefono == "0991111111" and resultado.modificado_por == 47
        assert campos == ["telefono"]


def test_repeticion_sql_conserva_autor_y_evitar_auditoria(sql_app, eventos_auditados):
    _, cliente = sql_app
    for _ in range(2):
        r = cliente.patch(RUTA, json={"estado": "A"})
        assert r.status_code == 200 and r.json()["modificadoPor"] == 9
    assert eventos_auditados == []


@pytest.mark.parametrize("metodo", ["get", "patch"])
def test_entidad_ausente_sql(engine, sql_app, metodo):
    _, cliente = sql_app
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM Organizacion.Entidad"))
    argumentos = {"json": {"estado": "I"}} if metodo == "patch" else {}
    r = getattr(cliente, metodo)(RUTA, **argumentos)
    assert r.status_code == 404 and r.json()["code"] == "ENTIDAD_NO_ENCONTRADA"


def test_fallo_sql_revierte_toda_la_edicion(
    engine, sql_app, monkeypatch, eventos_auditados
):
    _, cliente = sql_app
    original = repository.actualizar_entidad

    def escribir_y_fallar(conn, cambios, autor):
        original(conn, cambios, autor)
        # Error real de CHECK después del primer UPDATE dentro de la transacción.
        conn.execute(
            text("UPDATE Organizacion.Entidad SET Segmento = 0 WHERE IdEntidad = 1")
        )

    monkeypatch.setattr(repository, "actualizar_entidad", escribir_y_fallar)
    antes = cliente.get(RUTA).json()
    r = cliente.patch(
        RUTA, json={"telefono": "0991111111", "nombreComercial": "Cambio"}
    )
    assert r.status_code == 500
    assert cliente.get(RUTA).json() == antes
    assert eventos_auditados == []


def test_bloqueo_serializa_ediciones_y_reintento_conserva_otros_campos(engine, sql_app):
    with engine.connect() as primera, primera.begin():
        repository.obtener_entidad(primera, bloquear=True)
        repository.actualizar_entidad(
            primera, {"nombre_comercial": "Primera edición"}, 47
        )
        with engine.connect() as segunda:
            segunda.exec_driver_sql("SET LOCK_TIMEOUT 250")
            segunda.commit()
            with pytest.raises(DBAPIError, match="1222"):
                service.editar_entidad(
                    segunda, EntidadUpdate(telefono="0991111111"), 48
                )
            assert not segunda.in_transaction()
    with engine.connect() as segunda:
        resultado, campos = service.editar_entidad(
            segunda, EntidadUpdate(telefono="0991111111"), 48
        )
        assert resultado.nombre_comercial == "Primera edición"
        assert resultado.telefono == "0991111111" and resultado.modificado_por == 48
        assert campos == ["telefono"]


def test_ddl_impide_segunda_entidad(engine, sql_app):
    with pytest.raises(DBAPIError, match="CK_Entidad_UnaFila"), engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO Organizacion.Entidad
                    (IdEntidad, RUC, RazonSocial, FechaConstitucion,
                     RepresentanteLegal, IdentificacionRepresentante, ModificadoPor)
                VALUES (2, '0990000000001', 'Segunda entidad', '20000101',
                        'Representante', 'AB12345', 1)
            """)
        )


def test_put_http_crea_con_defaults_y_fecha_sql(
    engine, entidad_vacia, eventos_auditados
):
    _, cliente = entidad_vacia
    with engine.connect() as conn:
        antes = conn.exec_driver_sql(
            "SELECT CONVERT(datetime2, sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time')"
        ).scalar_one()
    r = cliente.put(RUTA, json=DATOS_CREACION)
    assert r.status_code == 201, r.text
    datos = r.json()
    with engine.connect() as conn:
        despues = conn.exec_driver_sql(
            "SELECT CONVERT(datetime2, sysdatetimeoffset() AT TIME ZONE 'SA Pacific Standard Time')"
        ).scalar_one()
        persistido = service.obtener_entidad(conn).model_dump(
            mode="json", by_alias=True
        )
    assert datos == persistido
    assert datos["idEntidad"] == 1 and datos["modificadoPor"] == 1
    assert datos["tipoOrganizacion"] == "Cooperativa de Ahorro y Credito"
    assert datos["estado"] == "A"
    assert antes <= datetime.fromisoformat(datos["fechaRegistro"]) <= despues
    for campo in (
        "nombreComercial",
        "segmento",
        "numeroResolucionSeps",
        "telefono",
        "email",
        "sitioWeb",
    ):
        assert datos[campo] is None
    assert (
        len(eventos_auditados) == 1 and eventos_auditados[0].accion == "CREAR_ENTIDAD"
    )
    for payload in (DATOS_CREACION, DATOS_CREACION | {"razonSocial": "Otra entidad"}):
        repetido = cliente.put(RUTA, json=payload)
        assert (
            repetido.status_code == 409
            and repetido.json()["code"] == "ENTIDAD_YA_EXISTE"
        )
    assert cliente.get(RUTA).json() == datos
    assert len(eventos_auditados) == 1


def test_put_http_crea_con_todos_los_campos(entidad_vacia):
    _, cliente = entidad_vacia
    datos = DATOS_CREACION | {
        "nombreComercial": "Nombre comercial SQL",
        "tipoOrganizacion": "Otra organización",
        "segmento": 5,
        "numeroResolucionSeps": "SEPS-ALTA",
        "telefono": "0991111111",
        "email": "alta@example.com",
        "sitioWeb": "https://example.org",
        "estado": "I",
    }
    r = cliente.put(RUTA, json=datos)
    assert r.status_code == 201, r.text
    assert {campo: r.json()[campo] for campo in datos} == datos
    assert cliente.get(RUTA).json() == r.json()


@pytest.mark.parametrize("nocount", ["ON", "OFF"])
def test_put_servicio_admite_nocount(engine, entidad_vacia, nocount):
    with engine.connect() as conn:
        conn.exec_driver_sql("SET NOCOUNT " + nocount)
        conn.commit()
        resultado = service.crear_entidad(
            conn, EntidadCreate.model_validate(DATOS_CREACION), 47
        )
        assert resultado.id_entidad == 1 and resultado.modificado_por == 47


def test_put_fallo_sql_revierte_insercion(
    engine, entidad_vacia, monkeypatch, eventos_auditados
):
    _, cliente = entidad_vacia
    original = repository.insertar_entidad

    def insertar_y_fallar(conn, datos, autor):
        original(conn, datos, autor)
        conn.execute(
            text("UPDATE Organizacion.Entidad SET Segmento = 0 WHERE IdEntidad = 1")
        )

    monkeypatch.setattr(repository, "insertar_entidad", insertar_y_fallar)
    r = cliente.put(RUTA, json=DATOS_CREACION)
    assert r.status_code == 500, r.text
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT COUNT(*) FROM Organizacion.Entidad")).scalar_one()
            == 0
        )
    assert eventos_auditados == []


def test_put_bloquea_rango_antes_de_crear_primera_fila(engine, entidad_vacia):
    with engine.connect() as primera, primera.begin():
        assert repository.obtener_entidad(primera, bloquear=True) is None
        with engine.connect() as segunda:
            segunda.exec_driver_sql("SET LOCK_TIMEOUT 250")
            segunda.commit()
            with pytest.raises(DBAPIError, match="1222"):
                service.crear_entidad(
                    segunda, EntidadCreate.model_validate(DATOS_CREACION), 48
                )
            assert not segunda.in_transaction()
        repository.insertar_entidad(
            primera, EntidadCreate.model_validate(DATOS_CREACION).model_dump(), 47
        )
    with engine.connect() as segunda:
        with pytest.raises(HTTPException, match="ENTIDAD_YA_EXISTE") as error:
            service.crear_entidad(
                segunda, EntidadCreate.model_validate(DATOS_CREACION), 48
            )
        assert error.value.status_code == 409
        assert service.obtener_entidad(segunda).modificado_por == 47


def test_dos_put_simultaneos_crean_una_sola_entidad(
    engine, entidad_vacia, eventos_auditados
):
    _, cliente = entidad_vacia
    barrera = Barrier(2, timeout=5)

    def crear():
        barrera.wait()
        return cliente.put(RUTA, json=DATOS_CREACION)

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        resultados = list(ejecutor.map(lambda _: crear(), range(2)))
    assert sorted(r.status_code for r in resultados) == [201, 409]
    conflicto = next(r for r in resultados if r.status_code == 409)
    assert conflicto.json()["code"] == "ENTIDAD_YA_EXISTE"
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT COUNT(*) FROM Organizacion.Entidad")).scalar_one()
            == 1
        )
    assert (
        len(eventos_auditados) == 1 and eventos_auditados[0].accion == "CREAR_ENTIDAD"
    )

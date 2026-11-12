"""Pruebas opt-in locales: DDL, estados y exclusión concurrente del guard.

Usa solo fixtures propias en el laboratorio existente; no escribe en Azure,
WorkOS ni tablas contables. Las fixtures se eliminan al terminar.
"""

import os

import pyodbc
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.modules.organizacion import service

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENCIAS_ESTADO_LOCAL_SQL_ENABLED") != "1",
    reason="Requiere autorización explícita del laboratorio local",
)
SERVER = "DESKTOP-OR5GE4R"
DATABASE = "CooperativaDB_AC01_Lab"
AGENCIA = "997"


def conectar():
    if os.environ.get("AGENCIAS_ESTADO_LOCAL_SQL_ENABLED") != "1":
        raise RuntimeError("Pruebas SQL de agencias deshabilitadas")
    raw = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={SERVER};DATABASE={DATABASE};Trusted_Connection=yes;"
        "Encrypt=yes;TrustServerCertificate=yes;APP=AgenciasEstado_Lab;",
        timeout=10,
    )
    try:
        fila = raw.execute("SELECT @@SERVERNAME, DB_NAME()").fetchone()
        if tuple(fila) != (SERVER, DATABASE):
            raise RuntimeError("Destino distinto del laboratorio permitido")
        raw.rollback()
    except BaseException:
        raw.close()
        raise
    return raw


@pytest.fixture
def engine():
    engine = create_engine("mssql+pyodbc://", creator=conectar, poolclass=NullPool)
    with engine.begin() as conn:
        if (
            conn.execute(
                text("SELECT 1 FROM Organizacion.Agencia WHERE IdAgencia=:id"),
                {"id": AGENCIA},
            ).first()
            or conn.execute(
                text("SELECT 1 FROM Catalogo.Paises WHERE CodigoPais='XQ'")
            ).first()
        ):
            pytest.fail(
                "Las claves de fixture ya existen; no se sobrescribe ningún registro"
            )
        conn.execute(
            text(
                "INSERT INTO Catalogo.Paises (CodigoPais,CodigoNumerico,NombrePais) VALUES ('XQ','997','AGENCIA ESTADO LAB')"
            )
        )
        ciudad = conn.execute(
            text(
                "INSERT INTO Catalogo.Ciudad (CodigoPais,Nombre,Provincia) OUTPUT inserted.IdCiudad VALUES ('XQ','AGENCIA ESTADO LAB','FICTICIA')"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO Organizacion.Agencia (IdAgencia,Codigo,TipoAgencia,IdCiudad,Estado) VALUES (:id,'AGE_ST_LAB','Sucursal',:ciudad,'A')"
            ),
            {"id": AGENCIA, "ciudad": ciudad},
        )
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM Organizacion.Agencia WHERE IdAgencia=:id AND Codigo='AGE_ST_LAB'"
                ),
                {"id": AGENCIA},
            )
            conn.execute(
                text(
                    "DELETE FROM Catalogo.Ciudad WHERE IdCiudad=:id AND CodigoPais='XQ'"
                ),
                {"id": ciudad},
            )
            conn.execute(
                text(
                    "DELETE FROM Catalogo.Paises WHERE CodigoPais='XQ' AND NombrePais='AGENCIA ESTADO LAB'"
                )
            )
        engine.dispose()


def poner_estado(engine, estado):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE Organizacion.Agencia SET Estado=:estado WHERE IdAgencia=:id"),
            {"id": AGENCIA, "estado": estado},
        )


@pytest.mark.parametrize(
    "anterior,nuevo,esperado",
    [
        ("A", "I", 200),
        ("I", "A", 200),
        ("A", "A", 200),
        ("I", "I", 200),
        ("C", "C", 200),
        ("C", "A", 409),
        ("C", "I", 409),
        ("A", "C", 409),
        ("I", "C", 409),
    ],
)
def test_transiciones_reales(engine, anterior, nuevo, esperado):
    poner_estado(engine, anterior)
    with engine.connect() as conn:
        if esperado == 200:
            resultado, previo = service.cambiar_estado(conn, AGENCIA, nuevo)
            assert resultado.estado == nuevo and previo == anterior
        else:
            with pytest.raises(HTTPException) as error:
                service.cambiar_estado(conn, AGENCIA, nuevo)
            assert error.value.status_code == 409
    with engine.connect() as conn:
        final = conn.execute(
            text("SELECT Estado FROM Organizacion.Agencia WHERE IdAgencia=:id"),
            {"id": AGENCIA},
        ).scalar_one()
        assert final == (nuevo if esperado == 200 else anterior)


@pytest.mark.parametrize("estado", ["A", "I", "C"])
def test_guard_real_para_altas_y_asignaciones(engine, estado):
    poner_estado(engine, estado)
    with engine.connect() as conn:
        if estado == "A":
            with conn.begin():
                assert (
                    service.exigir_agencia_destino_activa(conn, AGENCIA).estado == "A"
                )
        else:
            with pytest.raises(HTTPException) as error, conn.begin():
                service.exigir_agencia_destino_activa(conn, AGENCIA)
            assert error.value.status_code == 409


def test_guard_impide_desactivar_hasta_terminar_escritura_local(engine):
    with engine.connect() as asignacion, asignacion.begin():
        service.exigir_agencia_destino_activa(asignacion, AGENCIA)
        # Otra sesión no puede cambiar el estado mientras la asignación
        # conserva su transacción y el lock sobre la agencia activa.
        with pytest.raises(DBAPIError, match="1222"), engine.begin() as otra:
            otra.exec_driver_sql("SET LOCK_TIMEOUT 300")
            otra.execute(
                text("UPDATE Organizacion.Agencia SET Estado='I' WHERE IdAgencia=:id"),
                {"id": AGENCIA},
            )
    # Una vez liberado el lock, la otra sesión sí puede desactivar.
    with engine.connect() as otra:
        resultado, _ = service.cambiar_estado(otra, AGENCIA, "I")
        assert resultado.estado == "I"


def test_guard_404_real(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM Organizacion.Agencia WHERE IdAgencia=:id AND Codigo='AGE_ST_LAB'"
            ),
            {"id": AGENCIA},
        )
    with engine.connect() as conn, pytest.raises(HTTPException) as error:
        service.cambiar_estado(conn, AGENCIA, "A")
    assert error.value.status_code == 404

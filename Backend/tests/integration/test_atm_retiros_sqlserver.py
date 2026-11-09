"""ATM-03 opt-in: lecturas/locks SQL locales, sin retiros o reservas financieras."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.atm import retiros_repository as repo
from app.modules.atm.retiros_service import seleccionar_billetes
from tests.integration.atm_cambio_pin_sql_lab import (
    abrir,
    ejecutar,
    identificador,
    motor,
)


@pytest.fixture(scope="module")
def engine():
    if os.getenv("ATM03_LOCAL_SQL_ENABLED") != "1":
        pytest.skip("Laboratorio ATM03 local deshabilitado")
    base = "CooperativaDB_ATM03_Lab_" + uuid4().hex[:10]
    master = abrir("master")
    try:
        cur = master.cursor()
        if cur.execute("SELECT DB_ID(?)", base).fetchval() is not None:
            raise RuntimeError("Base existente: detener")
        cur.close()
        ejecutar(master, "master", "CREATE DATABASE " + identificador(base))
    finally:
        master.close()
    print("ATM03 base sintetica local conservada:", base)
    cn = abrir(base)
    try:
        ejecutar(cn, base, "CREATE SCHEMA ATM")
        ejecutar(cn, base, "CREATE SCHEMA Catalogo")
        ejecutar(cn, base, "CREATE SCHEMA Transacciones")
        ejecutar(
            cn,
            base,
            """
            CREATE TABLE Catalogo.Denominacion(IdDenominacion int PRIMARY KEY,
                Valor decimal(18,2),TipoPieza varchar(10),Estado char(1));
            CREATE TABLE ATM.Gaveta(IdGaveta int PRIMARY KEY,IdATM int,
                IdDenominacion int REFERENCES Catalogo.Denominacion(IdDenominacion),
                CantidadActual int,Capacidad int,Estado char(1));
            CREATE INDEX IX_Gaveta_ATM ON ATM.Gaveta(IdATM,IdGaveta);
            CREATE TABLE Transacciones.Transaccion(IdTransaccion bigint PRIMARY KEY,
                NumeroComprobante varchar(30),RegistroUnico char(12) NOT NULL UNIQUE,
                TipoTransaccion varchar(30),TipoOperacion varchar(10),IdCuenta int,
                IdTarjeta int,IdATM int,IdCanal int,MTI char(4),Monto decimal(18,2),
                CodigoProcesamiento char(6),CodigoRespuesta char(2),Estado varchar(12),
                FechaHoraSistema datetime2,STAN char(6),RRN char(12),Secuencial char(6));
            INSERT Catalogo.Denominacion VALUES(1,50,'Billete','A'),(2,20,'Billete','A');
            INSERT ATM.Gaveta VALUES(1,10,1,1,1000,'A'),(2,10,2,3,1000,'A');
            INSERT Transacciones.Transaccion(IdTransaccion,RegistroUnico,TipoOperacion,
                TipoTransaccion,IdCuenta,IdTarjeta,IdATM,IdCanal,MTI,Monto,Estado)
                VALUES(70,'ORIGINAL0070','Normal','Retiro',77,301,10,1,'0200',60,'Completada');
        """,
        )
    finally:
        cn.close()
    eng = motor(base, {}, "cooperativa")
    try:
        yield eng
    finally:
        eng.dispose()


def test_gavetas_y_combinacion_exacta_no_modifican_inventario(engine):
    from decimal import Decimal

    with engine.connect() as c:
        tx = c.begin()
        gavetas = repo.leer_gavetas(c, 10)
        billetes = seleccionar_billetes(Decimal(60), gavetas)
        assert [(b.id_gaveta, b.cantidad) for b in billetes] == [(2, 3)]
        assert repo.leer_gavetas(c, -1) == []
        tx.rollback()
    with engine.begin() as c:
        assert list(
            c.execute(
                text("SELECT CantidadActual FROM ATM.Gaveta ORDER BY IdGaveta")
            ).scalars()
        ) == [1, 3]


def test_registro_parametrizado_reutiliza_lectura_atm02(engine):
    with engine.begin() as c:
        row = repo.leer_registro(c, "ORIGINAL0070")
        assert row is not None and row["IdTransaccion"] == 70
        assert repo.leer_registro(c, "'; DROP TABLE ATM.Gaveta;--") is None
        assert c.scalar(text("SELECT COUNT(*) FROM ATM.Gaveta")) == 2


@pytest.mark.parametrize("registro", [False, True])
def test_concurrencia_serializa_lecturas_y_revierte(engine, registro):
    listo, intentado, liberar = Event(), Event(), Event()

    def bloquear(c):
        c.exec_driver_sql("SET LOCK_TIMEOUT 4000")
        if registro:
            assert repo.leer_registro(c, "NUEVOREG0001") is None
        else:
            assert len(repo.leer_gavetas(c, 10)) == 2

    def primero():
        with engine.connect() as c:
            tx = c.begin()
            try:
                bloquear(c)
                listo.set()
                assert liberar.wait(4)
            finally:
                tx.rollback()

    def segundo():
        assert listo.wait(4)
        with engine.connect() as c:
            tx = c.begin()
            try:
                intentado.set()
                bloquear(c)
            finally:
                tx.rollback()

    with ThreadPoolExecutor(2) as pool:
        a, b = pool.submit(primero), pool.submit(segundo)
        assert intentado.wait(4)
        time.sleep(0.25)
        solapamiento = not b.done()
        liberar.set()
        a.result(timeout=6)
        b.result(timeout=6)
    assert solapamiento
    with engine.begin() as c:
        assert c.scalar(text("SELECT SUM(CantidadActual) FROM ATM.Gaveta")) == 4
        assert c.scalar(text("SELECT COUNT(*) FROM Transacciones.Transaccion")) == 1


def test_timeout_de_bloqueo_no_reserva_ni_modifica(engine):
    with engine.connect() as a, engine.connect() as b:
        ta, tb = a.begin(), b.begin()
        try:
            repo.leer_gavetas(a, 10)
            b.exec_driver_sql("SET LOCK_TIMEOUT 200")
            with pytest.raises(DBAPIError, match="1222"):
                repo.leer_gavetas(b, 10)
        finally:
            tb.rollback()
            ta.rollback()
    with engine.begin() as c:
        assert c.scalar(text("SELECT SUM(CantidadActual) FROM ATM.Gaveta")) == 4

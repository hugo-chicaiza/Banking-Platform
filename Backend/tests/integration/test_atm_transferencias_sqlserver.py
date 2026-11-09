"""Repositorios de preparacion sobre SQL Server local opt-in.

Esquema minimo sintetico: NO ejecuta transferencias, asientos ni el autorizador.
Prueba consultas parametrizadas y locks reales; conserva la base creada.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.atm import transferencias_repository as repo
from tests.integration.atm_cambio_pin_sql_lab import (
    abrir,
    ejecutar,
    identificador,
    motor,
)


@pytest.fixture(scope="module")
def engine():
    if os.getenv("ATM05_LOCAL_SQL_ENABLED") != "1":
        pytest.skip("Laboratorio ATM05 local deshabilitado")
    base = "CooperativaDB_ATM05_Lab_" + uuid4().hex[:10]
    master = abrir("master")
    try:
        cur = master.cursor()
        if cur.execute("SELECT DB_ID(?)", base).fetchval() is not None:
            raise RuntimeError("Base existente: detener")
        cur.close()
        ejecutar(master, "master", "CREATE DATABASE " + identificador(base))
    finally:
        master.close()
    print("ATM05 base sintetica local conservada:", base)
    cn = abrir(base)
    try:
        ejecutar(cn, base, "CREATE SCHEMA Cuentas")
        ejecutar(cn, base, "CREATE SCHEMA Transacciones")
        ejecutar(
            cn,
            base,
            """
            CREATE TABLE Cuentas.Cuenta(IdCuenta int PRIMARY KEY,NumeroCuenta varchar(20) NOT NULL UNIQUE,Saldo decimal(18,2) NOT NULL);
            CREATE TABLE Transacciones.Transaccion(
                IdTransaccion bigint PRIMARY KEY,NumeroComprobante varchar(30) NOT NULL,
                RegistroUnico char(12) NOT NULL UNIQUE,MTI char(4) NOT NULL,
                TipoTransaccion varchar(30) NOT NULL,TipoOperacion varchar(10) NOT NULL,
                IdCuenta int NOT NULL,IdCuentaDestino int NULL,IdTarjeta int NULL,
                IdATM int NULL,IdCanal int NOT NULL,Monto decimal(18,2) NOT NULL,
                Estado varchar(12) NOT NULL,IdTransaccionRelacionada bigint NULL);
            INSERT Cuentas.Cuenta VALUES(1,'AH00000001',1000),(2,'AH00000002',200);
            INSERT Transacciones.Transaccion VALUES(70,'COMPROBANTE-SINTETICO','A1B2C3D4E5F6','0200','Transferencia_Enviada','Normal',1,2,301,10,1,150,'Completada',NULL);
        """,
        )
    finally:
        cn.close()
    eng = motor(base, {}, "cooperativa")
    try:
        yield eng
    finally:
        eng.dispose()


def test_sql_resolucion_y_parametrizacion(engine):
    with engine.begin() as c:
        assert repo.resolver_destino(c, "AH00000002") == 2
        assert repo.resolver_destino(c, "'; DROP TABLE Cuentas.Cuenta;--") is None
        assert c.scalar(text("SELECT COUNT(*) FROM Cuentas.Cuenta")) == 2


def test_sql_lectura_idempotencia_no_es_comprobante_http(engine):
    with engine.begin() as c:
        row = repo.leer_registro(c, "A1B2C3D4E5F6")
        assert (
            row is not None
            and row["IdCuentaDestino"] == 2
            and row["IdTransaccion"] == 70
        )
        assert repo.leer_registro(c, "SINREG000001") is None


def test_sql_bloqueo_ordenado_y_rollback_no_cambian_saldos(engine):
    with engine.connect() as c:
        tx = c.begin()
        repo.bloquear_cuentas(c, 2, 1)
        tx.rollback()
    with engine.begin() as c:
        assert list(
            c.execute(
                text("SELECT Saldo FROM Cuentas.Cuenta ORDER BY IdCuenta")
            ).scalars()
        ) == [1000, 200]
        repo.bloquear_cuentas(c, 1, 2)


@pytest.mark.parametrize("registro", [False, True])
def test_sql_concurrencia_serializa_cuentas_y_registro_sin_escribir(engine, registro):
    listo, intentado, liberar = Event(), Event(), Event()

    def bloqueo(c, orden):
        c.exec_driver_sql("SET LOCK_TIMEOUT 4000")
        if registro:
            assert repo.leer_registro(c, "NUEVOREG0001") is None
        else:
            repo.bloquear_cuentas(c, *orden)

    def primero():
        with engine.connect() as c:
            tx = c.begin()
            try:
                bloqueo(c, (2, 1))
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
                bloqueo(c, (1, 2))
            finally:
                tx.rollback()

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(primero)
        b = pool.submit(segundo)
        assert intentado.wait(4)
        time.sleep(0.25)
        solapamiento = not b.done()
        liberar.set()
        a.result(timeout=6)
        b.result(timeout=6)
    assert solapamiento
    with engine.begin() as c:
        assert c.scalar(text("SELECT COUNT(*) FROM Transacciones.Transaccion")) == 1
        assert c.scalar(text("SELECT SUM(Saldo) FROM Cuentas.Cuenta")) == 1200

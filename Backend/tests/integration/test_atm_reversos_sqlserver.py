"""ATM-08 opt-in: SQL local sintetico, sin flujo financiero ni acceso a Azure."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.atm import reversos_repository as repo
from app.modules.transacciones import repository as trx
from tests.integration.atm_cambio_pin_sql_lab import (
    abrir,
    ejecutar,
    identificador,
    motor,
)
from tests.integration.atm_sql_concurrency import comprobar_serializacion


@pytest.fixture(scope="module")
def engine():
    if os.getenv("ATM08_LOCAL_SQL_ENABLED") != "1":
        pytest.skip("Laboratorio ATM08 local deshabilitado")
    base = "CooperativaDB_ATM08_Lab_" + uuid4().hex[:10]
    master = abrir("master")
    try:
        cur = master.cursor()
        if cur.execute("SELECT DB_ID(?)", base).fetchval() is not None:
            raise RuntimeError("Base existente: detener")
        cur.close()
        ejecutar(master, "master", "CREATE DATABASE " + identificador(base))
    finally:
        master.close()
    print("ATM08 base sintetica local conservada:", base)
    cn = abrir(base)
    try:
        ejecutar(cn, base, "CREATE SCHEMA Cuentas")
        ejecutar(cn, base, "CREATE SCHEMA Transacciones")
        ejecutar(
            cn,
            base,
            """
            CREATE TABLE Cuentas.Cuenta(IdCuenta int PRIMARY KEY,IdAgencia varchar(10));
            CREATE TABLE Transacciones.Transaccion(
                IdTransaccion bigint PRIMARY KEY,NumeroComprobante varchar(30) UNIQUE,
                RegistroUnico char(12) NOT NULL CONSTRAINT UQ_Transaccion_RegistroUnico UNIQUE,
                MTI char(4), STAN char(6),RRN char(12),TipoOperacion varchar(10),
                TipoTransaccion varchar(30),IdCuenta int NOT NULL,IdCuentaDestino int NULL,
                IdTarjeta int NULL,IdCanal int,IdATM int NULL,IdAgencia varchar(10),
                IdJornadaCaja int NULL,IdTransaccionRelacionada bigint NULL,
                Monto decimal(18,2),CodigoRespuesta char(2),Estado varchar(12),
                IdFechaContable int,FechaHoraSistema datetime2,CreadoPor int,
                NumeroAutorizacion varchar(20));
            CREATE UNIQUE INDEX UX_Transaccion_UnReverso
                ON Transacciones.Transaccion(IdTransaccionRelacionada)
                WHERE TipoOperacion='Reverso';
            CREATE TABLE Cuentas.MovimientoTransaccion(IdMovimiento bigint PRIMARY KEY,
                IdTransaccion bigint,IdCuenta int,TipoMovimiento char(1),
                RolCuenta varchar(20),Monto decimal(18,2));
            INSERT Cuentas.Cuenta VALUES(77,'LAB');
            INSERT Transacciones.Transaccion(IdTransaccion,NumeroComprobante,RegistroUnico,TipoOperacion,
                TipoTransaccion,IdCuenta,IdATM,IdTarjeta,Estado,MTI,Monto)
                VALUES(70,'LAB070','ORIGINAL0070','Normal','Retiro',77,10,301,'Completada','0200',40),
                      (71,'LAB071','ORIGINAL0071','Normal','Retiro',77,10,301,'Completada','0200',40);
            INSERT Transacciones.Transaccion(IdTransaccion,NumeroComprobante,RegistroUnico,TipoOperacion,
                TipoTransaccion,IdCuenta,IdATM,IdTarjeta,Estado,MTI,IdTransaccionRelacionada,Monto)
                VALUES(72,'LAB072','REVERSO00070','Reverso','Retiro',77,10,301,'Completada','0400',70,40);
            INSERT Cuentas.MovimientoTransaccion VALUES(1,71,77,'D','Origen',40);
        """,
        )
    finally:
        cn.close()
    eng = motor(base, {}, "cooperativa")
    try:
        yield eng
    finally:
        eng.dispose()


def test_lecturas_reutilizadas_trx03_y_registro(engine):
    with engine.begin() as c:
        original = repo.leer_original(c, 71)
        assert original is not None and original["IdCuenta"] == 77
        assert repo.leer_original(c, -1) is None
        assert repo.tiene_reverso(c, 70) and not repo.tiene_reverso(c, 71)
        registro = repo.leer_registro(c, "REVERSO00070")
        assert registro is not None and registro["IdTransaccionRelacionada"] == 70
        assert (
            repo.leer_registro(c, "'; DROP TABLE Transacciones.Transaccion;--") is None
        )
        assert len(trx.movimientos_de_transaccion(c, 71)) == 1


@pytest.mark.parametrize(
    "registro,relacion", [("REVERSO00070", 71), ("REVERSO00099", 70)]
)
def test_indices_existentes_rechazan_duplicado_y_rollback(engine, registro, relacion):
    indice = (
        "UQ_Transaccion_RegistroUnico" if relacion == 71 else "UX_Transaccion_UnReverso"
    )
    with pytest.raises(IntegrityError, match=indice), engine.begin() as c:
        c.execute(
            text("""
            INSERT Transacciones.Transaccion(IdTransaccion,NumeroComprobante,RegistroUnico,TipoOperacion,
                IdCuenta,IdTransaccionRelacionada) VALUES(99,'LAB099',:registro,'Reverso',77,:relacion)
        """),
            {"registro": registro, "relacion": relacion},
        )
    with engine.begin() as c:
        assert c.scalar(text("SELECT COUNT(*) FROM Transacciones.Transaccion")) == 3


@pytest.mark.parametrize("por_registro", [False, True])
def test_locks_serializan_preparacion_sin_reversar(engine, por_registro):
    def bloquear(c):
        c.exec_driver_sql("SET LOCK_TIMEOUT 4000")
        if por_registro:
            assert repo.leer_registro(c, "NUEVOREG0001") is None
        else:
            assert repo.leer_original(c, 71) is not None
            assert not repo.tiene_reverso(c, 71)

    comprobar_serializacion(engine, bloquear)
    with engine.begin() as c:
        assert not repo.tiene_reverso(c, 71)
        original = repo.leer_original(c, 71)
        assert original is not None and original["Estado"] == "Completada"
        assert c.scalar(text("SELECT COUNT(*) FROM Cuentas.MovimientoTransaccion")) == 1

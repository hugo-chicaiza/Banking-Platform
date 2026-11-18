"""Rutas reales + repositorios + SQL local; sesión WorkOS simulada, sin Azure."""

import os
from dataclasses import replace
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.core.database.db import cooperativa
from app.core.security.auth import id_usuario_auditoria
from app.modules.parametros import service
from app.modules.parametros.router import router
from tests.integration.test_e112_sql_local import conectar, ejecutar
from tests.integration.test_e112_sql_local import sql as sql  # noqa: PLC0414
from tests.sesion import simular_sesion, usuario_con_roles

pytestmark = pytest.mark.skipif(
    os.environ.get("E112_LOCAL_SQL_ENABLED") != "1", reason="SQL Server local opt-in"
)
BASE = "/api/v1/parametros"


@pytest.fixture
def api_sql(sql):
    raw, base = sql
    ejecutar(raw, "001_exoneraciones.up.sql")
    raw.execute("""
        ALTER TABLE Transacciones.Comisiones ADD TipoComision varchar(30) NOT NULL DEFAULT 'Otro',
            Descripcion varchar(250) NOT NULL DEFAULT 'Laboratorio';
        ALTER TABLE Transacciones.Comisiones ADD DEFAULT 'A' FOR Estado;
        ALTER TABLE ProductosFinancieros.SubProducto ADD IdProducto int NOT NULL DEFAULT 1;
    """)
    raw.execute("""
        INSERT ProductosFinancieros.Producto VALUES (2);
        INSERT ProductosFinancieros.SubProducto (IdSubProducto,IdProducto) VALUES (2,2);
        INSERT Transacciones.TipoTransaccion VALUES ('Servicio_Lab','Servicio laboratorio',NULL,0,NULL,'A');
    """)
    raw.execute("CREATE SCHEMA Clientes")
    raw.execute("CREATE SCHEMA Cuentas")
    raw.execute("""
        CREATE TABLE Clientes.Cliente (IdCliente int PRIMARY KEY,TipoCliente varchar(10));
        INSERT Clientes.Cliente VALUES (1,'Natural');
        CREATE TABLE Cuentas.Cuenta (IdCuenta int PRIMARY KEY,IdCliente int,IdSubProducto int);
        INSERT Cuentas.Cuenta VALUES (1,1,1);
        CREATE TABLE Transacciones.Transaccion (
            IdTransaccion int IDENTITY PRIMARY KEY,IdCuenta int,TipoTransaccion varchar(30),IdCanal int,
            TipoOperacion varchar(10),Estado varchar(15),FechaHoraSistema datetime2);
    """)

    def conexion_db():
        c = conectar(base)
        c.autocommit = False
        return c

    motor = create_engine("mssql+pyodbc://", creator=conexion_db, poolclass=NullPool)

    def conexion():
        with motor.connect() as c:
            yield c

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[cooperativa] = conexion
    simular_sesion(app, replace(usuario_con_roles("ADMIN"), id_interno=900104))
    # Se ejecuta la dependencia UsuarioAuditoria real sobre la sesión simulada.
    app.dependency_overrides.pop(id_usuario_auditoria)
    try:
        with TestClient(app) as client:
            yield client, raw, motor
    finally:
        motor.dispose()


def nueva_comision():
    return {
        "codigoComision": "LAB104",
        "tipoComision": "Otro",
        "tipoCalculo": "Fijo",
        "valor": "0.05",
        "idCanal": 1,
        "codigoTipoTransaccion": "Servicio_Lab",
        "descripcion": "Servicio local",
        "vigenciaDesde": service.hoy().isoformat(),
    }


@pytest.fixture
def tarifas_para_solape(api_sql):
    client, raw, _ = api_sql
    inicio = service.hoy()
    vigente = {
        "idComision": 1,
        "idCanal": 2,
        "codigoTipoTransaccion": "Retiro",
        "vigenciaDesde": inicio.isoformat(),
        "vigenciaHasta": (inicio + timedelta(days=30)).isoformat(),
    }
    respuesta = client.post(BASE + "/comisiones", json=vigente)
    assert respuesta.status_code == 201, respuesta.text
    otra = raw.execute("""
        INSERT Transacciones.Comisiones
            (CodigoComision,TipoCalculo,Valor,IdCanal,VigenciaDesde,Estado)
        OUTPUT inserted.IdComision
        VALUES ('OTRA104','Fijo',0.75,2,'20200101','A')
    """).fetchval()
    return client, raw, vigente, otra


def configuracion_guardada(raw):
    return (
        [
            tuple(f)
            for f in raw.execute(
                "SELECT * FROM Transacciones.Comisiones ORDER BY IdComision"
            ).fetchall()
        ],
        [
            tuple(f)
            for f in raw.execute(
                "SELECT * FROM Transacciones.ComisionTipoTransaccion ORDER BY IdComisionTipoTransaccion"
            ).fetchall()
        ],
    )


@pytest.mark.parametrize("desde,hasta", [(0, 30), (5, 20), (20, None)])
def test_api_rechaza_asociar_otra_tarifa_con_solape_sin_filas_parciales(
    tarifas_para_solape, desde, hasta, eventos_auditados
):
    client, raw, vigente, otra = tarifas_para_solape
    antes = configuracion_guardada(raw)
    inicio = service.hoy()
    respuesta = client.post(
        BASE + "/comisiones",
        json={
            **vigente,
            "idComision": otra,
            "vigenciaDesde": (inicio + timedelta(days=desde)).isoformat(),
            "vigenciaHasta": (inicio + timedelta(days=hasta)).isoformat()
            if hasta is not None
            else None,
        },
    )
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["code"] == "COMISION_VIGENCIA_SOLAPADA"
    assert configuracion_guardada(raw) == antes
    assert len(antes[0]) == 4 and len(antes[1]) == 1
    assert (
        raw.execute(
            """
        SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion WHERE IdComision=?
    """,
            otra,
        ).fetchval()
        == 0
    )
    monto = raw.execute(
        """
        SELECT SUM(MontoComision) FROM Transacciones.fn_CalcularComision('Retiro',2,100,?)
    """,
        inicio,
    ).fetchval()
    assert monto == Decimal("0.45")
    assert eventos_auditados[-1].resultado == "Fallido"


def test_patch_valor_404_preserva_tarifa_y_asociacion_vigentes(tarifas_para_solape):
    client, raw, vigente, _ = tarifas_para_solape
    antes = configuracion_guardada(raw)
    respuesta = client.patch(
        BASE + "/comisiones/1",
        json={
            "valor": "0.99",
            "descripcion": "Este cambio tampoco debe persistirse",
        },
    )
    assert respuesta.status_code == 404, respuesta.text
    assert respuesta.json()["code"] == "FUNCION_NO_DISPONIBLE"
    assert configuracion_guardada(raw) == antes
    monto = raw.execute(
        """
        SELECT SUM(MontoComision) FROM Transacciones.fn_CalcularComision('Retiro',2,100,?)
    """,
        vigente["vigenciaDesde"],
    ).fetchval()
    assert monto == Decimal("0.45")


def test_rutas_comisiones_sql_y_actor(api_sql, eventos_auditados):
    client, raw, _ = api_sql
    assert len(client.get(BASE + "/comisiones").json()) == 3
    for id_, canal, tipo in [(1, 2, "Retiro"), (2, 3, "Transferencia_Enviada")]:
        payload = {
            "idComision": id_,
            "idCanal": canal,
            "codigoTipoTransaccion": tipo,
            "vigenciaDesde": service.hoy().isoformat(),
        }
        for _ in range(2):
            r = client.post(BASE + "/comisiones", json=payload)
            assert r.status_code == 201, r.text
            assert r.json()["asociaciones"][0]["registradoPor"] == 900104
    assert (
        raw.execute(
            "SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion"
        ).fetchval()
        == 2
    )
    r = client.post(BASE + "/comisiones", json=nueva_comision())
    assert r.status_code == 201, r.text
    id_ = r.json()["idComision"]
    r = client.patch(
        f"{BASE}/comisiones/{id_}",
        json={"descripcion": "Editada", "idCuentaContableIngreso": 10},
    )
    assert r.status_code == 200, r.text
    assert r.json()["descripcion"] == "Editada"
    assert r.json()["idCuentaContableIngreso"] == 10
    r = client.patch(
        f"{BASE}/comisiones/{id_}",
        json={"descripcion": "No debe quedar", "valor": "1.00"},
    )
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "FUNCION_NO_DISPONIBLE"
    fila = raw.execute(
        "SELECT Valor,Descripcion FROM Transacciones.Comisiones WHERE IdComision=?", id_
    ).fetchone()
    assert fila[0] == Decimal("0.05") and fila[1] == "Editada"
    assert eventos_auditados[-1].resultado == "Fallido"
    assert eventos_auditados[-1].usuario == 900104
    r = client.patch(f"{BASE}/comisiones/{id_}", json={"valor": "0.05"})
    assert r.status_code == 200
    assert (
        client.patch(BASE + "/comisiones/999", json={"estado": "I"}).status_code == 404
    )
    assert (
        client.post(
            BASE + "/comisiones", json={**nueva_comision(), "registradoPor": 12}
        ).status_code
        == 400
    )
    # Una nueva tarifa para la misma operación/canal no elude la aprobación.
    r = client.post(
        BASE + "/comisiones",
        json={**nueva_comision(), "codigoComision": "OTRA104", "valor": 9},
    )
    assert r.status_code == 409 and r.json()["code"] == "COMISION_VIGENCIA_SOLAPADA"
    assert raw.execute("SELECT COUNT(*) FROM Transacciones.Comisiones").fetchval() == 4
    r = client.post(
        BASE + "/comisiones",
        json={
            "idComision": 1,
            "idCanal": 1,
            "codigoTipoTransaccion": "Retiro",
            "vigenciaDesde": service.hoy().isoformat(),
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "CANAL_COMISION_INCOMPATIBLE"


def test_exoneracion_crud_y_calculo_automatico_sql(api_sql, eventos_auditados):
    client, raw, motor = api_sql
    r = client.post(BASE + "/comisiones", json=nueva_comision())
    assert r.status_code == 201, r.text
    id_comision = r.json()["idComision"]
    cuerpo = {
        "idComision": id_comision,
        "idSubProducto": 1,
        "porcentajeExonerado": 100,
        "operacionesGratisMes": 3,
        "vigenciaDesde": service.hoy().isoformat(),
    }
    r = client.post(BASE + "/exoneraciones", json=cuerpo)
    assert r.status_code == 201, r.text
    id_regla = r.json()["idExoneracion"]
    assert r.json()["creadoPor"] == 900104
    assert eventos_auditados[-1].accion == "PAR_EXONERACION_EDITADA"
    assert (
        len(client.get(BASE + f"/exoneraciones?idComision={id_comision}").json()) == 1
    )
    momento = datetime.combine(service.hoy(), time(12))

    def calcular(tipo="Servicio_Lab"):
        with motor.begin() as conn:
            return service.comision(
                conn, tipo, 1, 1, momento, monto_operacion=Decimal(100)
            )

    assert sum((c.monto_cobrar for c in calcular("Deposito")), Decimal(0)) == 0
    assert calcular()[0].monto_cobrar == 0 and calcular()[0].id_exoneracion == id_regla
    for _ in range(2):
        raw.execute(
            "INSERT Transacciones.Transaccion VALUES (1,'Servicio_Lab',1,'Normal','Completada',?)",
            momento - timedelta(hours=1),
        )
    # Otro mes/canal/tipo y los reversos no consumen este cupo.
    for tipo, canal, operacion, fecha in [
        ("Servicio_Lab", 1, "Normal", momento.replace(day=1) - timedelta(days=1)),
        ("Servicio_Lab", 2, "Normal", momento - timedelta(hours=1)),
        ("Retiro", 1, "Normal", momento - timedelta(hours=1)),
        ("Servicio_Lab", 1, "Reverso", momento - timedelta(hours=1)),
    ]:
        raw.execute(
            "INSERT Transacciones.Transaccion VALUES (1,?,?,?,'Completada',?)",
            tipo,
            canal,
            operacion,
            fecha,
        )
    # La tercera operación es gratis.
    assert calcular()[0].monto_cobrar == 0
    raw.execute(
        "INSERT Transacciones.Transaccion VALUES (1,'Servicio_Lab',1,'Normal','Completada',?)",
        momento - timedelta(minutes=1),
    )
    assert (
        calcular()[0].monto_cobrar == Decimal("0.05")
        and calcular()[0].id_exoneracion is None
    )
    r = client.patch(
        BASE + f"/exoneraciones/{id_regla}",
        json={"porcentajeExonerado": 50, "operacionesGratisMes": None},
    )
    assert r.status_code == 200, r.text
    assert calcular()[0].monto_cobrar == Decimal("0.03")
    assert client.post(BASE + "/exoneraciones", json=cuerpo).status_code == 409
    assert (
        client.patch(
            BASE + f"/exoneraciones/{id_regla}", json={"estado": "I"}
        ).status_code
        == 200
    )
    assert calcular()[0].monto_cobrar == Decimal("0.05")
    for pct in (-1, 101):
        assert (
            client.post(
                BASE + "/exoneraciones", json={**cuerpo, "porcentajeExonerado": pct}
            ).status_code
            == 400
        )
    assert (
        client.post(BASE + "/exoneraciones", json={**cuerpo, "idProducto": 2}).json()[
            "code"
        ]
        == "SUBPRODUCTO_INCOMPATIBLE"
    )
    assert (
        client.patch(BASE + "/exoneraciones/999", json={"estado": "I"}).status_code
        == 404
    )


def test_vigencias_precedencia_y_patches_sql(api_sql):
    client, raw, motor = api_sql
    id_comision = client.post(BASE + "/comisiones", json=nueva_comision()).json()[
        "idComision"
    ]
    cuerpo = {
        "idComision": id_comision,
        "porcentajeExonerado": 50,
        "vigenciaDesde": service.hoy().isoformat(),
    }
    r = client.post(
        BASE + "/exoneraciones",
        json={
            **cuerpo,
            "vigenciaDesde": (service.hoy() - timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "VIGENCIA_PASADA"
    assert client.post(BASE + "/exoneraciones", json=cuerpo).status_code == 201
    r = client.post(
        BASE + "/exoneraciones",
        json={**cuerpo, "idSubProducto": 1, "porcentajeExonerado": 100},
    )
    assert r.status_code == 201, r.text
    id_regla = r.json()["idExoneracion"]
    with motor.begin() as conn:
        cobro = service.comision(
            conn,
            "Servicio_Lab",
            1,
            1,
            datetime.combine(service.hoy(), time(12)),
            monto_operacion=Decimal(100),
        )[0]
        assert cobro.monto_cobrar == 0 and cobro.id_exoneracion == id_regla
    raw.execute(
        "UPDATE Transacciones.ExoneracionComision SET VigenciaDesde=? WHERE IdExoneracion=?",
        service.hoy() - timedelta(days=1),
        id_regla,
    )
    r = client.patch(
        BASE + f"/exoneraciones/{id_regla}", json={"porcentajeExonerado": 25}
    )
    assert r.status_code == 422 and r.json()["code"] == "VIGENCIA_PASADA"
    assert (
        client.patch(
            BASE + f"/exoneraciones/{id_regla}", json={"estado": "I"}
        ).status_code
        == 200
    )

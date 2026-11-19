"""BOV real en SQL Server local: migración, persistencia, rollback y concurrencia."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from threading import Barrier
from typing import Any, cast

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.boveda import service
from app.modules.boveda.schemas import ArqueoBovedaRequest
from app.modules.boveda.solicitudes import service as solicitudes
from app.modules.boveda.solicitudes.schemas import SolicitudMovimientoRequest
from tests.integration.boveda_sql_lab import LaboratorioBoveda
from tests.sesion import USUARIO

pytestmark = pytest.mark.skipif(
    os.getenv("BOV_LOCAL_SQL") != "1",
    reason="Laboratorio local BOV deshabilitado (BOV_LOCAL_SQL=1)",
)
OPERADOR = replace(USUARIO, roles=("SUPERVISOR",), id_interno=7)
APROBADOR = replace(OPERADOR, id_interno=9)


@pytest.fixture
def motor(monkeypatch):
    lab = LaboratorioBoveda()
    # crear() también valida la migración dos veces antes de insertar datos ficticios.
    try:
        engine = lab.crear()
        monkeypatch.setattr(service, "validar_participante_boveda", lambda *args: None)
        monkeypatch.setattr(
            service.contabilidad, "ahora_ecuador", lambda: datetime(2026, 11, 16, 10)
        )
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO Organizacion.Agencia (IdAgencia,Codigo,TipoAgencia,Estado,FechaCreacion,IdCiudad,IdEntidad)
                VALUES ('001','LAB1','Matriz','A',GETDATE(),1,1),('002','LAB2','Sucursal','A',GETDATE(),1,1);
                INSERT INTO Catalogo.Denominacion (TipoPieza,Valor,Descripcion,Estado,FechaRegistro)
                VALUES ('Billete',20,'LAB 20','A',GETDATE()),('Billete',10,'LAB 10','A',GETDATE());
                INSERT INTO Contabilidad.FechaContable (Fecha,NumeroDiaSemana,NombreDiaSemana,EsFeriado,FechaRegistro,HoraCorte)
                VALUES ('20261116',1,'Lunes',0,GETDATE(),'19:00');
                INSERT INTO Contabilidad.PeriodoContable (Anio,Mes,Estado) VALUES (2026,11,'ABIERTO');
                INSERT INTO Contabilidad.TiposAsiento (Codigo,Nombre,Descripcion,EsManual,Estado)
                VALUES ('LAB_BOV','LAB','Datos ficticios',0,'A');
                INSERT INTO Contabilidad.CuentasContables (CodigoCuenta,NombreCuenta,Naturaleza,Saldo,Estado,FechaCreacion,EsImputable,EsCuentaValuacion)
                VALUES ('110105','LAB efectivo','DEUDORA',0,1,GETDATE(),1,0),('110110','LAB contraparte','DEUDORA',0,1,GETDATE(),1,0);
                INSERT INTO Boveda.Boveda (CodigoBoveda,TipoBoveda,IdAgencia,LimiteMaximo,LimiteMinimo,SaldoActual)
                VALUES ('LAB1','General','001',1000,0,200),('LAB2','General','002',1000,0,200);
                INSERT INTO Boveda.BovedaDenominacion (IdBoveda,IdDenominacion,CantidadActual) VALUES (1,1,10),(2,1,10);
                INSERT INTO Contabilidad.PlantillaBoveda (IdAgencia,TipoMovimiento,Naturaleza,IdCuentaDebito,IdCuentaCredito,IdTipoAsiento)
                SELECT a.IdAgencia,t.tipo,t.naturaleza,1,2,1 FROM Organizacion.Agencia a
                CROSS JOIN (VALUES ('ProvisionExterna','I'),('EnvioExcedente','E'),('Traslado','E'),('Traslado','I'),('AjusteFaltante','E'),('AjusteSobrante','I')) t(tipo,naturaleza);
            """)
            )
        yield engine
    finally:
        lab.borrar()


def movimiento(tipo="ProvisionExterna", cantidad=2, **extra):
    return SolicitudMovimientoRequest.model_validate(
        {
            "tipoMovimiento": tipo,
            "desglose": [{"idDenominacion": 1, "cantidad": cantidad}],
            **extra,
        }
    )


def test_sql_historial_arqueos_filtros_paginacion_y_legado(motor):
    from datetime import date

    datos = ArqueoBovedaRequest.model_validate(
        {
            "tipoArqueo": "Programado",
            "idUsuarioTestigo": 9,
            "desglose": [{"idDenominacion": 1, "cantidad": 10}],
        }
    )
    with motor.connect() as conn:
        for _ in range(3):
            service.registrar_arqueo(conn, OPERADOR, 7, 1, datos, "local")
        service.aprobar_arqueo(conn, APROBADOR, 9, 1, "local")
        pagina = service.listar_arqueos(
            conn,
            OPERADOR,
            1,
            date(2026, 11, 16),
            date(2026, 11, 16),
            None,
            "Programado",
            1,
            2,
        )
        assert pagina.total == 3
        assert [a.id_arqueo_boveda for a in pagina.items] == [3, 2]
        fuera = service.listar_arqueos(conn, OPERADOR, 1, None, None, None, None, 4, 2)
        assert fuera.total == 3 and fuera.items == []
        aprobadas = service.listar_arqueos(
            conn, OPERADOR, 1, None, None, "APROBADO", None, 1, 20
        )
        assert aprobadas.total == 1 and aprobadas.items[0].id_usuario_aprobador == 9
        assert (
            service.listar_arqueos(
                conn, OPERADOR, 1, date(2026, 11, 17), None, None, None, 1, 20
            ).total
            == 0
        )
        with conn.begin():
            conn.execute(
                text("""
                UPDATE Boveda.ArqueoBoveda SET SaldoTeorico=NULL, SaldoFisico=NULL,
                    IdMovimientoCorte=NULL WHERE IdArqueoBoveda=3
            """)
            )
        historicos = service.listar_arqueos(
            conn, OPERADOR, 1, None, None, None, None, 1, 20
        )
        assert historicos.items[0].saldo_teorico is None
        assert historicos.items[0].diferencia is None


def ejecutar_movimiento(conn, usuario, actor, id_boveda, datos, ip, clave=None):
    solicitud = solicitudes.crear(conn, usuario, actor, id_boveda, datos, ip, clave)
    aprobador = replace(usuario, id_interno=9)
    return solicitudes.aprobar(
        conn, aprobador, 9, solicitud.id_solicitud_movimiento, ip
    )


def test_sql_provision_traslado_paginacion_y_reintento(motor):
    with motor.connect() as conn:
        listado = service.listar_bovedas(conn, OPERADOR, None, None)
        assert len(listado) == 1 and listado[0].total_desglose == 200
        primera = ejecutar_movimiento(
            conn, OPERADOR, 7, 1, movimiento(), "local", "prov-1"
        )
        assert primera[0].saldo_posterior == 240
        assert (
            ejecutar_movimiento(conn, OPERADOR, 7, 1, movimiento(), "local", "prov-1")
            == primera
        )
        par = ejecutar_movimiento(
            conn, OPERADOR, 7, 1, movimiento("Traslado", idBovedaContraparte=2), "local"
        )
        assert len(par) == 2
        assert par[0].id_movimiento_relacionado == par[1].id_movimiento
        assert service.obtener_boveda(conn, OPERADOR, 1).saldo_actual == 200
        pagina = service.listar_movimientos(
            conn, OPERADOR, 1, None, None, None, 1, 10, "idMovimiento,asc"
        )
        assert pagina.total == 2 and len(pagina.items[0].desglose) == 1
        assert (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM Contabilidad.AsientoContable WHERE Estado='CONTABILIZADO' AND TotalDebito=TotalCredito"
                )
            ).scalar_one()
            == 3
        )


def test_sql_fallo_contable_revierte_ambas_bovedas(motor):
    with motor.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM Contabilidad.PlantillaBoveda WHERE IdAgencia='002' AND TipoMovimiento='Traslado'"
            )
        )
    with motor.connect() as conn:
        with pytest.raises(HTTPException) as error:
            ejecutar_movimiento(
                conn,
                OPERADOR,
                7,
                1,
                movimiento("Traslado", idBovedaContraparte=2),
                "local",
            )
        detalle = cast(dict[str, Any], error.value.detail)
        assert isinstance(detalle, dict)
        assert detalle["code"] == "PLANTILLA_BOVEDA_NO_CONFIGURADA"
        assert (
            conn.execute(
                text("SELECT SUM(SaldoActual) FROM Boveda.Boveda")
            ).scalar_one()
            == 400
        )
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM Boveda.MovimientoBoveda")
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM Contabilidad.AsientoContable")
            ).scalar_one()
            == 0
        )


def test_sql_arqueo_mixto_aprobacion_y_no_repeticion(motor):
    datos = ArqueoBovedaRequest.model_validate(
        {
            "tipoArqueo": "Sorpresivo",
            "idUsuarioTestigo": 9,
            "desglose": [
                {"idDenominacion": 1, "cantidad": 9},
                {"idDenominacion": 2, "cantidad": 2},
            ],
        }
    )
    with motor.connect() as conn:
        arqueo = service.registrar_arqueo(conn, OPERADOR, 7, 1, datos, "local")
        aprobada = service.aprobar_arqueo(
            conn, APROBADOR, 9, arqueo.id_arqueo_boveda, "local"
        )
        assert aprobada.estado == "APROBADO" and aprobada.diferencia == 0
        assert len(aprobada.ids_movimientos_ajuste) == 2
        assert service.obtener_boveda(conn, OPERADOR, 1).saldo_actual == 200
        with pytest.raises(HTTPException) as error:
            service.aprobar_arqueo(conn, APROBADOR, 9, arqueo.id_arqueo_boveda, "local")
        detalle = cast(dict[str, Any], error.value.detail)
        assert isinstance(detalle, dict)
        assert detalle["code"] == "ARQUEO_NO_REGISTRADO"


def test_sql_clave_concurrente_no_duplica_movimientos(motor):
    barrera = Barrier(2)

    def provisionar():
        with motor.connect() as conn:
            barrera.wait(timeout=10)
            return ejecutar_movimiento(
                conn, OPERADOR, 7, 1, movimiento(), "local", "misma-clave"
            )[0].id_movimiento

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: provisionar(), range(2)))
    assert ids[0] == ids[1]
    with motor.connect() as conn:
        assert service.obtener_boveda(conn, OPERADOR, 1).saldo_actual == 240
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM Contabilidad.AsientoContable")
            ).scalar_one()
            == 1
        )


def test_sql_movimiento_posterior_impide_aprobar_conteo(motor):
    datos = ArqueoBovedaRequest.model_validate(
        {
            "tipoArqueo": "Programado",
            "idUsuarioTestigo": 9,
            "desglose": [{"idDenominacion": 1, "cantidad": 9}],
        }
    )
    with motor.connect() as conn:
        arqueo = service.registrar_arqueo(conn, OPERADOR, 7, 1, datos, "local")
        ejecutar_movimiento(conn, OPERADOR, 7, 1, movimiento(), "local")
        with pytest.raises(HTTPException) as error:
            service.aprobar_arqueo(conn, APROBADOR, 9, arqueo.id_arqueo_boveda, "local")
        detalle = cast(dict[str, Any], error.value.detail)
        assert isinstance(detalle, dict)
        assert detalle["code"] == "ARQUEO_DESACTUALIZADO"
        assert (
            conn.execute(text("SELECT Estado FROM Boveda.ArqueoBoveda")).scalar_one()
            == "REGISTRADO"
        )


def test_sql_dos_egresos_concurrentes_no_sobregiran(motor):
    barrera = Barrier(2)

    def egresar():
        with motor.connect() as conn:
            barrera.wait(timeout=10)
            try:
                ejecutar_movimiento(
                    conn,
                    OPERADOR,
                    7,
                    1,
                    movimiento("EnvioExcedente", cantidad=8),
                    "local",
                )
                return "ok"
            except HTTPException as error:
                detalle = cast(dict[str, Any], error.detail)
                assert isinstance(detalle, dict)
                return detalle["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(lambda _: egresar(), range(2)))
    assert sorted(resultados) == ["SALDO_INSUFICIENTE", "ok"]
    with motor.connect() as conn:
        assert service.obtener_boveda(conn, OPERADOR, 1).saldo_actual == 40
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM Boveda.MovimientoBoveda")
            ).scalar_one()
            == 1
        )


def test_sql_solicitud_pendiente_y_rechazo_no_mueven_efectivo(motor):
    with motor.connect() as conn:
        solicitud = solicitudes.crear(conn, OPERADOR, 7, 1, movimiento(), "local", None)
        assert solicitud.estado == "PENDIENTE"
        assert service.obtener_boveda(conn, OPERADOR, 1).saldo_actual == 200
        resuelta = solicitudes.resolver_sin_ejecucion(
            conn,
            APROBADOR,
            9,
            solicitud.id_solicitud_movimiento,
            "RECHAZADA",
            "No procede",
            "local",
        )
        assert resuelta.estado == "RECHAZADA"
        assert resuelta.id_usuario_resolucion == 9
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM Boveda.MovimientoBoveda")
            ).scalar_one()
            == 0
        )


def test_sql_aprobaciones_simultaneas_de_distintos_usuarios(motor):
    with motor.connect() as conn:
        solicitud = solicitudes.crear(conn, OPERADOR, 7, 1, movimiento(), "local", None)
    barrera = Barrier(2)

    def aprobar(actor):
        with motor.connect() as conn:
            barrera.wait(timeout=10)
            try:
                resultado = solicitudes.aprobar(
                    conn,
                    replace(APROBADOR, id_interno=actor),
                    actor,
                    solicitud.id_solicitud_movimiento,
                    "local",
                )
                assert (
                    resultado[0].id_solicitud_movimiento
                    == solicitud.id_solicitud_movimiento
                )
                return "ok"
            except HTTPException as error:
                return cast(dict[str, Any], error.detail)["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(aprobar, [9, 10]))
    assert sorted(resultados) == ["SOLICITUD_MOVIMIENTO_RESUELTA", "ok"]
    with motor.connect() as conn:
        assert service.obtener_boveda(conn, OPERADOR, 1).saldo_actual == 240
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM Boveda.MovimientoBoveda")
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize(
    "tabla,asignacion",
    [
        ("SolicitudMovimientoBoveda", "Monto=999"),
        ("SolicitudMovimientoBovedaDenominacion", "Cantidad=99"),
    ],
)
def test_sql_solicitudes_no_se_editan(motor, tabla, asignacion):
    with motor.connect() as conn:
        solicitud = solicitudes.crear(conn, OPERADOR, 7, 1, movimiento(), "local", None)
    with pytest.raises(DBAPIError), motor.begin() as conn:
        conn.execute(
            text(
                f"UPDATE Boveda.{tabla} SET {asignacion} WHERE IdSolicitudMovimiento=:id"
            ),
            {"id": solicitud.id_solicitud_movimiento},
        )
    with motor.connect() as conn:
        assert (
            solicitudes.obtener(conn, OPERADOR, solicitud.id_solicitud_movimiento).monto
            == 40
        )


def test_sql_traslado_con_trigger_contable_se_ejecuta_una_sola_vez(motor):
    with motor.begin() as conn:
        conn.execute(
            text("""
            CREATE TRIGGER Contabilidad.trg_AsientoContable_PeriodoLab
            ON Contabilidad.AsientoContable AFTER INSERT AS
            BEGIN
                SET NOCOUNT ON;
                IF EXISTS (
                    SELECT 1 FROM inserted i
                    JOIN Contabilidad.PeriodoContable p
                      ON p.Anio=YEAR(i.FechaAsiento) AND p.Mes=MONTH(i.FechaAsiento)
                    WHERE p.Estado='CERRADO'
                )
                    THROW 56007, N'El periodo del asiento esta cerrado.', 1;
            END;
            """)
        )

    with motor.connect() as conn:
        solicitud = solicitudes.crear(
            conn,
            OPERADOR,
            7,
            1,
            movimiento("Traslado", idBovedaContraparte=2),
            "local",
            None,
        )
        primera = solicitudes.aprobar(
            conn, APROBADOR, 9, solicitud.id_solicitud_movimiento, "local"
        )
        repetida = solicitudes.aprobar(
            conn, APROBADOR, 9, solicitud.id_solicitud_movimiento, "local"
        )
        assert primera == repetida
        assert len(primera) == 2
        assert len({m.id_asiento_contable for m in primera}) == 2
        assert service.obtener_boveda(conn, OPERADOR, 1).saldo_actual == 160
        admin = replace(OPERADOR, roles=("ADMIN",))
        assert service.obtener_boveda(conn, admin, 2).saldo_actual == 240
        assert (
            solicitudes.obtener(
                conn, OPERADOR, solicitud.id_solicitud_movimiento
            ).estado
            == "EJECUTADA"
        )
        assert (
            conn.execute(
                text("""
            SELECT COUNT(*) FROM Contabilidad.AsientoContable
            WHERE Estado='CONTABILIZADO' AND TotalDebito=40 AND TotalCredito=40
        """)
            ).scalar_one()
            == 2
        )
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM Boveda.MovimientoBoveda")
            ).scalar_one()
            == 2
        )


def test_sql_fallo_al_vincular_revierte_toda_aprobacion(motor, monkeypatch):
    from app.modules.boveda.solicitudes import repository as repo

    with motor.connect() as conn:
        solicitud = solicitudes.crear(conn, OPERADOR, 7, 1, movimiento(), "local", None)

        def fallar(*args):
            raise RuntimeError("fallo de persistencia simulado")

        monkeypatch.setattr(repo, "vincular", fallar)
        with pytest.raises(RuntimeError):
            solicitudes.aprobar(
                conn, APROBADOR, 9, solicitud.id_solicitud_movimiento, "local"
            )
        assert (
            solicitudes.obtener(
                conn, OPERADOR, solicitud.id_solicitud_movimiento
            ).estado
            == "PENDIENTE"
        )
        assert service.obtener_boveda(conn, OPERADOR, 1).saldo_actual == 200
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM Contabilidad.AsientoContable")
            ).scalar_one()
            == 0
        )

"""Opt-in SQL Server real exclusivamente local. Ninguna conexion a Azure."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.core.security.pin_version import version_desde_fecha
from app.modules.atm import cambio_pin_service as svc
from app.modules.atm import repository, service, session
from app.modules.atm.terminal_auth import TerminalAutenticado
from app.modules.tarjetas import repository as tarjetas_repo
from app.modules.tarjetas import service as tarjetas_service
from tests.integration.atm_cambio_pin_sql_lab import motor, preparar
from tests.integration.test_atm_cambio_pin_local import Laboratorio
from tests.tarjetas_hsm import HSM, PAN


@pytest.fixture(scope="module")
def laboratorio_sql():
    if os.getenv("ATM06_LOCAL_SQL_ENABLED") != "1":
        pytest.skip("ATM06 SQL local deshabilitado; requiere activacion explicita")
    if not os.getenv("ATM06_SCHEMA_SOURCE_SEG") or not os.getenv(
        "ATM06_SCHEMA_SOURCE_COOP"
    ):
        pytest.fail("Se requieren fuentes de metadatos del laboratorio local")
    bases = preparar()
    print("ATM06 bases locales conservadas:", bases)
    fallos = {}
    engines = {tipo: motor(base, fallos, tipo) for tipo, base in bases.items()}
    try:
        yield engines, fallos
    finally:
        for engine in engines.values():
            engine.dispose()


@pytest.fixture
def sql(laboratorio_sql, monkeypatch):
    engines, fallos = laboratorio_sql
    assert not fallos
    monkeypatch.setattr(svc, "get_engine", engines.__getitem__)
    monkeypatch.setattr(session, "get_engine", engines.__getitem__)
    monkeypatch.setattr(service, "get_engine", engines.__getitem__)
    monkeypatch.setattr(service, "obtener_hsm", lambda: HSM)
    monkeypatch.setattr(svc, "obtener_hsm", lambda: HSM)
    monkeypatch.setattr(svc, "revalidar_terminal", lambda *a: None)
    tarjeta = int(uuid4().hex[:7], 16)
    fecha = datetime(2026, 1, 1)
    offset, pvk = HSM.generar_offset(*HSM.construir_pin_block("4826", PAN), PAN)
    cifrado, ref = HSM.cifrar_pan(PAN, tarjeta)
    with engines["cooperativa"].begin() as c:
        c.execute(
            text(
                "INSERT Tarjeta.Tarjeta VALUES(:id,1,1,'Cliente','Sintetico',1,'Debito','20260101','20990101','Activa',:hash)"
            ),
            {"id": tarjeta, "hash": service.hash_pan(PAN)},
        )
    with engines["seguridad"].begin() as c:
        c.execute(
            text(
                "INSERT Tarjetas.TarjetaPIN(ID_Tarjeta,TienePINAsignado,FechaAsignacion,Estado,PINOffset,ReferenciaClavePVK,RequiereCambio) VALUES(:id,1,:fecha,'Activo',:offset,:pvk,0)"
            ),
            {"id": tarjeta, "fecha": fecha, "offset": offset, "pvk": pvk},
        )
        c.execute(
            text("INSERT Pruebas.PanFicticio VALUES(:id,:pan,:ref)"),
            {"id": tarjeta, "pan": cifrado, "ref": ref},
        )
    sesion = session.SesionATM(
        str(uuid4()),
        datetime.now(UTC) + timedelta(seconds=300),
        1,
        tarjeta,
        (1,),
        False,
        version_desde_fecha(fecha),
    )
    terminal = TerminalAutenticado("laboratorio", "ATM00001", 900, b"")

    def cambiar():
        svc.cambiar_pin(
            sesion, terminal, Laboratorio.solicitud("4826", "9274"), "127.0.0.1"
        )

    def operacion():
        with engines["seguridad"].connect() as c:
            return str(
                c.scalar(
                    text(
                        "SELECT IdOperacion FROM Tarjetas.CambioPINATMOperacion WHERE ID_Tarjeta=:id"
                    ),
                    {"id": tarjeta},
                )
            )

    def comprobar():
        with engines["seguridad"].connect() as c:
            op = c.execute(
                text(
                    "SELECT Estado,VersionNueva FROM Tarjetas.CambioPINATMOperacion WHERE ID_Tarjeta=:id"
                ),
                {"id": tarjeta},
            ).one()
            pin = repository.obtener_pin_para_verificacion(c, tarjeta)
            assert (
                op.Estado == "COMPLETADA"
                and pin is not None
                and not pin["requiere_cambio"]
            )
            assert pin["fecha_asignacion"] == op.VersionNueva
            assert repository.sesion_atm_revocada(c, sesion.jti)
        with engines["cooperativa"].connect() as c:
            assert (
                c.scalar(
                    text(
                        "SELECT COUNT(*) FROM Tarjeta.CambioPINATMAplicado WHERE IdTarjeta=:id"
                    ),
                    {"id": tarjeta},
                )
                == 1
            )
            assert (
                c.scalar(
                    text(
                        "SELECT COUNT(*) FROM Tarjeta.TarjetaHis WHERE IdTarjeta=:id AND TipoEvento='CambioPin'"
                    ),
                    {"id": tarjeta},
                )
                == 1
            )

    return SimpleNamespace(
        engines=engines,
        fallos=fallos,
        tarjeta=tarjeta,
        sesion=sesion,
        terminal=terminal,
        cambiar=cambiar,
        operacion=operacion,
        comprobar=comprobar,
    )


def test_sql_cambio_completo(sql):
    sql.cambiar()
    sql.comprobar()
    svc.recuperar_cambio_pin(sql.operacion())
    sql.comprobar()
    with sql.engines["cooperativa"].connect() as c:
        historial = tarjetas_service.obtener_historial(c, sql.tarjeta, 1, 10, None)
    cambios = [
        evento for evento in historial.items if evento.tipo_evento == "CambioPin"
    ]
    assert len(cambios) == 1
    assert cambios[0].origen == "Cliente"
    assert cambios[0].resultado == "COMPLETADO"


def test_sql_activacion_inicial(sql):
    from dataclasses import replace

    with sql.engines["cooperativa"].begin() as c:
        c.execute(
            text("UPDATE Tarjeta.Tarjeta SET Estado='Generada' WHERE IdTarjeta=:id"),
            {"id": sql.tarjeta},
        )
    with sql.engines["seguridad"].begin() as c:
        c.execute(
            text(
                "UPDATE Tarjetas.TarjetaPIN SET RequiereCambio=1 WHERE ID_Tarjeta=:id"
            ),
            {"id": sql.tarjeta},
        )
    svc.cambiar_pin(
        replace(sql.sesion, cambio_pin_requerido=True, cuentas=()),
        sql.terminal,
        Laboratorio.solicitud("4826", "9274"),
        None,
    )
    sql.comprobar()
    with sql.engines["cooperativa"].connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT COUNT(*) FROM Tarjeta.TarjetaHis WHERE IdTarjeta=:id AND TipoEvento='Activacion'"
                ),
                {"id": sql.tarjeta},
            )
            == 1
        )


@pytest.mark.parametrize(
    "fase", ["insertar_operacion", "aplicar_cooperativa", "avanzar", "finalizar"]
)
def test_sql_commit_confirmado_pero_respuesta_perdida(sql, monkeypatch, fase):
    original = getattr(svc.repo, fase)

    def ambiguo(*args, **kwargs):
        original(*args, **kwargs)
        sql.fallos["cooperativa" if fase == "aplicar_cooperativa" else "seguridad"] = (
            True
        )

    monkeypatch.setattr(svc.repo, fase, ambiguo)
    with pytest.raises(HTTPException) as e:
        sql.cambiar()
    assert e.value.status_code == 503
    monkeypatch.setattr(svc.repo, fase, original)
    svc.recuperar_cambio_pin(sql.operacion())
    sql.comprobar()


def test_sql_concurrencia(sql):
    def ejecutar(_):
        try:
            sql.cambiar()
            return 204
        except HTTPException as e:
            return e.status_code

    with ThreadPoolExecutor(2) as executor:
        estados = list(executor.map(ejecutar, range(2)))
    assert sorted(estados) == [204, 401]
    sql.comprobar()


def test_sql_pendiente_bloquea_tar05_y_autorizacion(sql, monkeypatch):
    original = svc.repo.aplicar_cooperativa

    def falla(*a):
        raise svc.no_confirmado()

    monkeypatch.setattr(svc.repo, "aplicar_cooperativa", falla)
    with pytest.raises(HTTPException):
        sql.cambiar()
    with sql.engines["seguridad"].connect() as c:
        actual = repository.obtener_asignacion_pin_actual(c, sql.tarjeta)
        assert actual is not None and actual["coordinacion_pendiente"]
    with (
        sql.engines["cooperativa"].connect() as c,
        pytest.raises(HTTPException) as auth,
    ):
        asyncio.run(
            service.autenticar_pin_ficticio_atm(
                c, sql.tarjeta, HSM.construir_pin_block("5837", PAN)[0], "TEST-KEY-01"
            )
        )
    assert auth.value.status_code == 503
    with sql.engines["seguridad"].connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT IntentosFallidos FROM Tarjetas.TarjetaPIN WHERE ID_Tarjeta=:id"
                ),
                {"id": sql.tarjeta},
            )
            == 0
        )
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError), sql.engines["seguridad"].begin() as c:
        tarjetas_repo.guardar_pin_generado(c, sql.tarjeta, "1234", "SIM-PVK-01", True)
    monkeypatch.setattr(svc.repo, "aplicar_cooperativa", original)
    svc.recuperar_cambio_pin(sql.operacion())
    sql.comprobar()


def test_sql_recuperadores_concurrentes_no_duplican(sql, monkeypatch):
    original = svc.repo.aplicar_cooperativa

    def interrumpir(*a):
        raise svc.no_confirmado()

    monkeypatch.setattr(svc.repo, "aplicar_cooperativa", interrumpir)
    with pytest.raises(HTTPException):
        sql.cambiar()
    monkeypatch.setattr(svc.repo, "aplicar_cooperativa", original)
    operacion = sql.operacion()
    with ThreadPoolExecutor(2) as executor:
        list(executor.map(svc.recuperar_cambio_pin, [operacion, operacion]))
    sql.comprobar()


def test_sql_fallo_despues_de_historial_revierte_marcador_y_activacion(
    sql, monkeypatch
):
    from dataclasses import replace

    with sql.engines["cooperativa"].begin() as c:
        c.execute(
            text("UPDATE Tarjeta.Tarjeta SET Estado='Generada' WHERE IdTarjeta=:id"),
            {"id": sql.tarjeta},
        )
    with sql.engines["seguridad"].begin() as c:
        c.execute(
            text(
                "UPDATE Tarjetas.TarjetaPIN SET RequiereCambio=1 WHERE ID_Tarjeta=:id"
            ),
            {"id": sql.tarjeta},
        )
    original = svc.repo.aplicar_cooperativa

    def interrumpir(conn, op):
        original(conn, op)
        raise svc.no_confirmado()

    monkeypatch.setattr(svc.repo, "aplicar_cooperativa", interrumpir)
    with pytest.raises(HTTPException):
        svc.cambiar_pin(
            replace(sql.sesion, cambio_pin_requerido=True, cuentas=()),
            sql.terminal,
            Laboratorio.solicitud("4826", "9274"),
            None,
        )
    with sql.engines["cooperativa"].connect() as c:
        assert (
            c.scalar(
                text("SELECT Estado FROM Tarjeta.Tarjeta WHERE IdTarjeta=:id"),
                {"id": sql.tarjeta},
            )
            == "Generada"
        )
        assert (
            c.scalar(
                text("SELECT COUNT(*) FROM Tarjeta.TarjetaHis WHERE IdTarjeta=:id"),
                {"id": sql.tarjeta},
            )
            == 0
        )
        assert (
            c.scalar(
                text(
                    "SELECT COUNT(*) FROM Tarjeta.CambioPINATMAplicado WHERE IdTarjeta=:id"
                ),
                {"id": sql.tarjeta},
            )
            == 0
        )
    monkeypatch.setattr(svc.repo, "aplicar_cooperativa", original)
    svc.recuperar_cambio_pin(sql.operacion())
    sql.comprobar()

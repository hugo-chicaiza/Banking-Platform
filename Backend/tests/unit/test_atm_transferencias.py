"""Preparacion parcial ATM-05, sin conexiones ni escritores financieros."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.modules.atm import repository, saldo_repository, service, session
from app.modules.atm import transferencias_service as svc
from app.modules.atm.schemas import AtmTransferenciaRequest
from app.modules.atm.terminal_auth import TerminalAutenticado
from app.modules.transacciones.dependencias import DependenciasNoConfiguradas
from tests.pin_version import FECHA_PIN, VERSION_PIN, DriverLimitesSQL

BODY = {
    "idCuentaOrigen": 1,
    "numeroCuentaDestino": "AH00000002",
    "monto": 150,
    "registroUnico": "A1B2C3D4E5F6",
}


@pytest.fixture
def preparacion(monkeypatch):
    conn = MagicMock()
    conn.invalidated = False
    conn.connection.driver_connection = DriverLimitesSQL()
    sesion = session.SesionATM(
        str(uuid4()),
        datetime.now(UTC) + timedelta(seconds=300),
        10,
        301,
        (1,),
        False,
        VERSION_PIN,
    )
    terminal = TerminalAutenticado("laboratorio", "ATM00001", 900, b"")
    entrada = AtmTransferenciaRequest.model_validate(BODY)
    origen = {
        "Estado": "Activa",
        "Saldo": Decimal(1000),
        "SaldoRetenido": Decimal(100),
        "Ahora": datetime(2026, 11, 9, 10),
        "IdCliente": 100,
    }
    destino = {**origen, "Saldo": Decimal(200), "IdCliente": 200}
    tarjeta = {
        "id_cuenta": 1,
        "estado_tarjeta": "Activa",
        "pin_asignado": True,
        "fecha_expiracion": datetime(2099, 1, 1),
        "id_cliente": 999,
    }
    monkeypatch.setattr(svc, "revalidar_terminal", lambda *a: None)
    monkeypatch.setattr(saldo_repository, "bloquear_contexto", Mock())
    monkeypatch.setattr(
        service, "validar_terminal", lambda *a: {"id_atm": 10, "id_canal": 1}
    )
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda *a: tarjeta)
    monkeypatch.setattr(session, "require_sesion_atm", lambda s: s)
    monkeypatch.setattr(session, "require_sesion_pin_actual", lambda s: s)
    monkeypatch.setattr(svc.repo, "resolver_destino", Mock(return_value=2))
    monkeypatch.setattr(svc.repo, "leer_registro", Mock(return_value=None))
    monkeypatch.setattr(
        saldo_repository, "leer_cuenta", lambda conn, id: origen if id == 1 else destino
    )
    autorizar = Mock(
        return_value={"CodigoRespuesta": "00", "Comision": Decimal("1.25")}
    )
    monkeypatch.setattr(svc, "autorizar_operacion", autorizar)
    return SimpleNamespace(
        conn=conn,
        sesion=sesion,
        terminal=terminal,
        entrada=entrada,
        origen=origen,
        destino=destino,
        tarjeta=tarjeta,
        autorizar=autorizar,
    )


def preparar(p):
    return svc.prevalidar_transferencia(p.conn, p.sesion, p.terminal, p.entrada)


def code(error):
    return cast(dict[str, str], error.detail)["code"]


def test_entrada_acepta_numero_con_prefijo_y_usd_global():
    entrada = AtmTransferenciaRequest.model_validate(BODY)
    assert entrada.monto == Decimal(150)
    assert "AH00000002" not in repr(entrada)
    assert set(entrada.model_dump(by_alias=True)) == set(BODY)


@pytest.mark.parametrize(
    "monto", [0, -1, True, "150.00", 0.001, 1e20, float("nan"), float("inf"), None]
)
def test_monto_invalido_rechazado(monto):
    with pytest.raises(ValidationError):
        AtmTransferenciaRequest.model_validate({**BODY, "monto": monto})


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("idCuentaOrigen", True),
        ("idCuentaOrigen", 0),
        ("idCuentaOrigen", 2147483648),
        ("numeroCuentaDestino", ""),
        ("numeroCuentaDestino", "X" * 21),
        ("numeroCuentaDestino", "A\nB"),
        ("numeroCuentaDestino", " AH00000002"),
        ("registroUnico", "corta"),
    ],
)
def test_entrada_invalida(campo, valor):
    with pytest.raises(ValidationError):
        AtmTransferenciaRequest.model_validate({**BODY, campo: valor})


def test_no_se_anade_moneda_o_exoneracion_al_contrato():
    for campo in ("moneda", "idMoneda", "exonerada", "comision"):
        with pytest.raises(ValidationError):
            AtmTransferenciaRequest.model_validate({**BODY, campo: 0})


def test_prevalidacion_no_es_transferencia_y_siempre_revierte(preparacion):
    p = preparacion
    resultado = preparar(p)
    assert resultado.id_moneda == 840
    assert resultado.comision_calculada == Decimal("1.25")
    assert resultado.id_transaccion_candidata is None
    # La tarjeta adicional se autoriza por vinculacion y JWT, no por igualar personas.
    assert p.tarjeta["id_cliente"] != p.origen["IdCliente"]
    p.conn.begin.return_value.rollback.assert_called_once()
    p.conn.commit.assert_not_called()
    ids = [c.args[1]["id"] for c in p.conn.execute.call_args_list]
    assert ids == [1, 2]
    assert all(
        "UPDLOCK, HOLDLOCK" in str(c.args[0]) for c in p.conn.execute.call_args_list
    )
    assert p.conn.connection.driver_connection.lock_timeout == -1


def test_bloqueo_inverso_tambien_es_determinista():
    conn = MagicMock()
    svc.repo.bloquear_cuentas(conn, 20, 3)
    assert [c.args[1]["id"] for c in conn.execute.call_args_list] == [3, 20]


def test_origen_no_autorizado_no_consulta_sql(preparacion):
    p = preparacion
    p.sesion = replace(p.sesion, cuentas=(9,))
    with pytest.raises(HTTPException) as e:
        preparar(p)
    assert e.value.status_code == 404
    p.conn.begin.assert_not_called()


@pytest.mark.parametrize(
    "caso,estado,codigo",
    [
        ("destino_ausente", 404, "CUENTA_DESTINO_NO_ENCONTRADA"),
        ("destino_inactivo", 404, "CUENTA_DESTINO_NO_ENCONTRADA"),
        ("misma", 422, "CUENTA_DESTINO_IGUAL_ORIGEN"),
        ("origen_inactivo", 409, "CUENTA_NO_ACTIVA"),
        ("vinculacion", 404, "CUENTA_NO_ENCONTRADA"),
        ("tarjeta", 403, "TARJETA_NO_ACTIVA"),
        ("vencida", 403, "TARJETA_NO_ACTIVA"),
    ],
)
def test_validaciones_de_cuentas_y_tarjeta(
    preparacion, monkeypatch, caso, estado, codigo
):
    p = preparacion
    if caso == "destino_ausente":
        monkeypatch.setattr(svc.repo, "resolver_destino", lambda *a: None)
    elif caso == "misma":
        monkeypatch.setattr(svc.repo, "resolver_destino", lambda *a: 1)
    elif caso == "destino_inactivo":
        p.destino["Estado"] = "Cerrada"
    elif caso == "origen_inactivo":
        p.origen["Estado"] = "Bloqueada"
    elif caso == "vinculacion":
        p.tarjeta["id_cuenta"] = 2
    elif caso == "vencida":
        p.tarjeta["fecha_expiracion"] = FECHA_PIN
    else:
        p.tarjeta["estado_tarjeta"] = "Generada"
    with pytest.raises(HTTPException) as e:
        preparar(p)
    assert e.value.status_code == estado and code(e.value) == codigo
    p.conn.begin.return_value.rollback.assert_called_once()
    p.autorizar.assert_not_called()


def test_reasignacion_numero_destino_no_produce_toctou(preparacion, monkeypatch):
    monkeypatch.setattr(svc.repo, "resolver_destino", Mock(side_effect=[2, 3]))
    with pytest.raises(HTTPException) as e:
        preparar(preparacion)
    assert e.value.status_code == 404


@pytest.mark.parametrize("codigo", ["05", "61", "65"])
def test_no_inventa_mapeos_del_autorizador(preparacion, codigo):
    preparacion.autorizar.return_value = {
        "CodigoRespuesta": codigo,
        "Comision": Decimal(1),
    }
    with pytest.raises(HTTPException) as e:
        preparar(preparacion)
    assert e.value.status_code == 501


@pytest.mark.parametrize("saldo,codigo", [(Decimal(1000), "51"), (Decimal(250), "00")])
def test_fondos_incluyen_comision(preparacion, saldo, codigo):
    preparacion.origen["Saldo"] = saldo
    preparacion.autorizar.return_value = {
        "CodigoRespuesta": codigo,
        "Comision": Decimal("1.25"),
    }
    with pytest.raises(HTTPException) as e:
        preparar(preparacion)
    assert code(e.value) == "FONDOS_INSUFICIENTES"


@pytest.mark.parametrize("valor", [None, Decimal(-1), Decimal("NaN")])
def test_comision_invalida_no_se_convierte_en_gratuita(preparacion, valor):
    preparacion.autorizar.return_value = {"CodigoRespuesta": "00", "Comision": valor}
    with pytest.raises(HTTPException) as e:
        preparar(preparacion)
    assert e.value.status_code == 503


def anterior(p):
    return {
        "IdTransaccion": 70,
        "TipoOperacion": "Normal",
        "TipoTransaccion": "Transferencia_Enviada",
        "IdCuenta": 1,
        "IdCuentaDestino": 2,
        "IdTarjeta": 301,
        "IdATM": 10,
        "IdCanal": 1,
        "Monto": p.entrada.monto,
    }


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("TipoOperacion", "Reverso"),
        ("TipoTransaccion", "Consulta"),
        ("IdCuenta", 2),
        ("IdCuentaDestino", 3),
        ("IdTarjeta", 302),
        ("IdATM", 11),
        ("IdCanal", 9),
        ("Monto", Decimal(1)),
    ],
)
def test_registro_reutilizado_se_rechaza(preparacion, monkeypatch, campo, valor):
    row = {**anterior(preparacion), campo: valor}
    monkeypatch.setattr(svc.repo, "leer_registro", lambda *a: row)
    with pytest.raises(HTTPException) as e:
        preparar(preparacion)
    assert e.value.status_code == 409 and code(e.value) == "REGISTRO_UNICO_REUTILIZADO"


def test_registro_compatible_solo_es_candidato_no_comprobante(preparacion, monkeypatch):
    monkeypatch.setattr(svc.repo, "leer_registro", lambda *a: anterior(preparacion))
    assert preparar(preparacion).id_transaccion_candidata == 70


def test_error_sql_revierte_y_no_expone_detalles(preparacion):
    preparacion.autorizar.side_effect = SQLAlchemyError("DETALLES_SQL_NO_PUBLICOS")
    with pytest.raises(HTTPException) as e:
        preparar(preparacion)
    assert e.value.status_code == 503
    assert "DETALLES_SQL_NO_PUBLICOS" not in str(e.value.detail)
    preparacion.conn.begin.return_value.rollback.assert_called_once()


def test_barrera_no_puede_habilitarse_por_dependencias_ajenas(preparacion):
    p = preparacion
    for deps in (DependenciasNoConfiguradas(), MagicMock()):
        with pytest.raises(HTTPException) as e:
            svc.solicitar_transferencia(p.sesion, p.terminal, p.entrada, deps)
        assert e.value.status_code == 501
    p.conn.begin.assert_not_called()

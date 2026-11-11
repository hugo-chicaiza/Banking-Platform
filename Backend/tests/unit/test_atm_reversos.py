"""ATM-08 parcial: contrato, elegibilidad y rollback, sin SQL real."""

from datetime import datetime
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.modules.atm import reversos_service as svc
from app.modules.atm import service, session
from app.modules.atm.schemas import AtmReversoRequest
from tests.pin_version import DriverLimitesSQL
from tests.unit.test_atm_transferencias import preparacion  # noqa: F401 -- fixture sintetico compartido.

BODY = {"idTransaccion": 70, "motivo": "TIMEOUT"}


@pytest.fixture
def reverso(request, monkeypatch):
    p = request.getfixturevalue("preparacion")
    p.entrada = AtmReversoRequest.model_validate(BODY)
    p.original = {"IdCuenta": 1, "TipoOperacion": "Normal", "Estado": "Completada"}
    p.conn.connection.driver_connection = DriverLimitesSQL()
    monkeypatch.setattr(svc, "revalidar_terminal", lambda *a: None)
    monkeypatch.setattr(svc.repo, "leer_original", lambda *a: p.original)
    monkeypatch.setattr(svc.repo, "tiene_reverso", lambda *a: False)
    monkeypatch.setattr(
        svc.trx, "movimientos_de_transaccion", lambda *a: [{"Monto": 40}]
    )
    return p


def preparar(p):
    return svc.prevalidar_reverso(p.conn, p.sesion, p.terminal, p.entrada)


@pytest.mark.parametrize(
    "motivo", ["FALLA_DISPENSADOR", "TIMEOUT", "CLIENTE_NO_RETIRO_EFECTIVO", "OTRO"]
)
def test_contrato_exacto(motivo):
    entrada = AtmReversoRequest.model_validate({**BODY, "motivo": motivo})
    assert set(entrada.model_dump(by_alias=True)) == set(BODY)


@pytest.mark.parametrize(
    "cambio",
    [
        {"idTransaccion": 0},
        {"idTransaccion": True},
        {"idTransaccion": "70"},
        {"idTransaccion": 2**63},
        {"motivo": "otro"},
        {"registroUnico": "A1B2C3D4E5F6"},
        {"comision": 0},
        {"idCuenta": 1},
    ],
)
def test_contrato_estricto_sin_campos_inventados(cambio):
    with pytest.raises(ValidationError):
        AtmReversoRequest.model_validate({**BODY, **cambio})


def test_preparacion_no_confirma_operacion(reverso):
    resultado = preparar(reverso)
    assert resultado.id_original == 70 and resultado.id_cuenta == 1
    reverso.conn.begin.return_value.rollback.assert_called_once()
    reverso.conn.begin.return_value.commit.assert_not_called()
    reverso.conn.commit.assert_not_called()


@pytest.mark.parametrize(
    "original",
    [
        None,
        {"IdCuenta": 9},
        {"IdCuenta": 1, "Estado": "Pendiente", "TipoOperacion": "Normal"},
        {"IdCuenta": 1, "Estado": "Rechazada", "TipoOperacion": "Normal"},
        {"IdCuenta": 1, "Estado": "Completada", "TipoOperacion": "Reverso"},
    ],
)
def test_no_reversable(reverso, original):
    reverso.original = original
    with pytest.raises(HTTPException) as e:
        preparar(reverso)
    assert e.value.status_code == 409
    assert cast(dict[str, str], e.value.detail)["code"] == "TRANSACCION_NO_REVERSABLE"
    reverso.conn.begin.return_value.rollback.assert_called_once()


@pytest.mark.parametrize("estado", [True, False])
def test_duplicado_por_estado_o_relacion(reverso, monkeypatch, estado):
    if estado:
        reverso.original["Estado"] = "Reversada"
    else:
        monkeypatch.setattr(svc.repo, "tiene_reverso", lambda *a: True)
    with pytest.raises(HTTPException) as e:
        preparar(reverso)
    assert cast(dict[str, str], e.value.detail)["code"] == "TRANSACCION_YA_REVERSADA"


def test_consulta_sin_movimientos_no_es_reverso_financiero(reverso, monkeypatch):
    monkeypatch.setattr(svc.trx, "movimientos_de_transaccion", lambda *a: [])
    with pytest.raises(HTTPException) as e:
        preparar(reverso)
    assert e.value.status_code == 409


@pytest.mark.parametrize(
    "caso",
    [
        "terminal",
        "tarjeta",
        "vinculacion",
        "vencida",
        "revocada",
        "version",
        "restringida",
    ],
)
def test_revalida_seguridad_antes_de_preparar(reverso, monkeypatch, caso):
    if caso == "terminal":
        monkeypatch.setattr(service, "validar_terminal", lambda *a: {"id_atm": 99})
    elif caso == "tarjeta":
        reverso.tarjeta["estado_tarjeta"] = "Bloqueada"
    elif caso == "vinculacion":
        reverso.tarjeta["id_cuenta"] = 9
    elif caso == "vencida":
        reverso.tarjeta["fecha_expiracion"] = datetime(2000, 1, 1)
    else:
        nombre = {
            "revocada": "require_sesion_atm",
            "version": "require_sesion_pin_actual",
            "restringida": "require_sesion_operativa",
        }[caso]

        def denegar(*a):
            raise HTTPException(401)

        monkeypatch.setattr(session, nombre, denegar)
    with pytest.raises(HTTPException):
        preparar(reverso)
    reverso.conn.begin.return_value.rollback.assert_called_once()


def test_sql_falla_cerrado_y_revierte(reverso, monkeypatch):
    def fallar(*a):
        raise SQLAlchemyError("DETALLE_SQL_PRIVADO")

    monkeypatch.setattr(svc.repo, "tiene_reverso", fallar)
    with pytest.raises(HTTPException) as e:
        preparar(reverso)
    assert e.value.status_code == 503
    assert "DETALLE_SQL_PRIVADO" not in str(e.value.detail)
    reverso.conn.begin.return_value.rollback.assert_called_once()


def test_deps_genericas_no_abren_barrera(reverso):
    with pytest.raises(HTTPException) as e:
        svc.solicitar_reverso(
            reverso.sesion, reverso.terminal, reverso.entrada, MagicMock()
        )
    assert e.value.status_code == 501
    reverso.conn.begin.assert_not_called()

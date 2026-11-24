from datetime import date, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.cuentas import autorizados
from app.modules.cuentas.schemas import AutorizadoCuentaCreate


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setattr(autorizados, "hoy", lambda: date(2026, 11, 24))
    monkeypatch.setattr(autorizados, "edad_mayoria", lambda *_: 18)
    return MagicMock()


def _fila(datos):
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = datos
    return result


def test_alta_rechaza_cuenta_de_otra_agencia(conn):
    conn.execute.return_value = _fila(None)
    with pytest.raises(HTTPException) as exc:
        autorizados.agregar(
            conn,
            501,
            "002",
            AutorizadoCuentaCreate.model_validate(
                {"idClienteAutorizado": 9, "rol": "Firmante"}
            ),
        )
    assert exc.value.status_code == 404
    assert conn.execute.call_count == 1


def test_alta_asocia_relacion_vigente(conn, monkeypatch):
    monkeypatch.setattr(
        autorizados,
        "relacion_vigente",
        lambda *_: {
            "IdRelacion": 11,
            "IdClienteRelacionado": 9,
            "FechaFin": date(2027, 1, 1),
        },
    )
    nacimiento, duplicado, insercion = MagicMock(), MagicMock(), MagicMock()
    nacimiento.scalar_one_or_none.return_value = date(1990, 1, 1)
    duplicado.first.return_value = None
    insercion.scalar_one.return_value = 55
    conn.execute.side_effect = [
        _fila({"IdCliente": 7, "Estado": "PendienteDeposito"}),
        nacimiento,
        duplicado,
        insercion,
    ]
    resultado = autorizados.agregar(
        conn,
        501,
        "001",
        AutorizadoCuentaCreate.model_validate(
            {"idClienteAutorizado": 9, "rol": "Tutor"}
        ),
    )
    assert resultado.id_cuenta_autorizado == 55
    assert resultado.vigente
    assert resultado.fecha_fin == date(2027, 1, 1)
    assert conn.execute.call_args.args[1]["relacion"] == 11


@pytest.mark.parametrize("revocado", [None, datetime(2026, 11, 24, 14)])
def test_fin_es_inmediato_e_idempotente(conn, revocado):
    conn.execute.side_effect = [
        _fila({"IdCliente": 7, "Estado": "Activa"}),
        _fila(
            {
                "FechaInicio": date(2026, 11, 24),
                "FechaFin": None,
                "RevocadoEn": revocado,
            }
        ),
        MagicMock(),
    ]
    autorizados.finalizar(conn, 501, 55, "001")
    assert conn.execute.call_count == (3 if revocado is None else 2)
    if revocado is None:
        assert "RevocadoEn=SYSUTCDATETIME()" in str(conn.execute.call_args.args[0])

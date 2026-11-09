"""ATM-03 parcial: preparacion, inventario inmutable y barrera financiera."""

from copy import deepcopy
from decimal import Decimal
from itertools import product
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.modules.atm import retiros_service as svc
from app.modules.atm.schemas import AtmRetiroRequest
from tests.unit.test_atm_transferencias import preparacion  # noqa: F401 -- fixture sintetico, sin SQL real.

BODY = {"idCuenta": 1, "monto": 150, "registroUnico": "A1B2C3D4E5F6"}


def gaveta(id, valor, cantidad, **cambios):
    return {
        "IdGaveta": id,
        "IdDenominacion": id,
        "Valor": Decimal(valor),
        "CantidadActual": cantidad,
        "Capacidad": 1000,
        "Estado": "A",
        "TipoPieza": "Billete",
        "EstadoDenominacion": "A",
        **cambios,
    }


@pytest.fixture
def retiro(request, monkeypatch):
    p = request.getfixturevalue("preparacion")
    p.entrada = AtmRetiroRequest.model_validate(BODY)
    p.gavetas = [gaveta(1, 50, 2), gaveta(2, 20, 5), gaveta(3, 10, 4)]
    monkeypatch.setattr(svc, "revalidar_terminal", lambda *a: None)
    monkeypatch.setattr(svc.repo, "leer_registro", lambda *a: None)
    monkeypatch.setattr(svc.repo, "leer_gavetas", lambda *a: p.gavetas)
    monkeypatch.setattr(svc, "autorizar_operacion", p.autorizar)
    return p


def preparar(p):
    return svc.prevalidar_retiro(p.conn, p.sesion, p.terminal, p.entrada)


@pytest.mark.parametrize(
    "cambio",
    [
        {"monto": True},
        {"monto": "150"},
        {"monto": 0},
        {"monto": -1},
        {"monto": 1.001},
        {"monto": float("nan")},
        {"monto": float("inf")},
        {"monto": 1e20},
        {"moneda": "USD"},
        {"exonerada": True},
        {"comision": 0},
        {"idCuenta": True},
        {"registroUnico": "corto"},
        {"fechaHoraDispositivo": 123},
        {"fechaHoraDispositivo": "fecha-falsa"},
    ],
)
def test_entrada_estricta(cambio):
    with pytest.raises(ValidationError):
        AtmRetiroRequest.model_validate({**BODY, **cambio})


@pytest.mark.parametrize(
    "fecha",
    [None, "2026-11-09T12:30:00", "2026-11-09T17:30:00Z", "2026-11-09T12:30:00-05:00"],
)
def test_fecha_de_dispositivo_solo_informativa(fecha):
    entrada = AtmRetiroRequest.model_validate({**BODY, "fechaHoraDispositivo": fecha})
    assert (
        entrada.fecha_hora_dispositivo is None
        or entrada.fecha_hora_dispositivo.hour == 12
    )


def test_preparacion_revierte_y_no_es_comprobante(retiro):
    antes = deepcopy(retiro.gavetas)
    resultado = preparar(retiro)
    assert resultado.id_moneda == 840 and resultado.comision_calculada == Decimal(
        "1.25"
    )
    assert resultado.id_transaccion_candidata is None
    valores = {g["IdGaveta"]: g["Valor"] for g in retiro.gavetas}
    assert sum(valores[b.id_gaveta] * b.cantidad for b in resultado.billetes) == 150
    assert retiro.gavetas == antes
    retiro.conn.begin.return_value.rollback.assert_called_once()
    retiro.conn.commit.assert_not_called()
    retiro.conn.begin.return_value.commit.assert_not_called()
    assert retiro.autorizar.call_args.kwargs["fecha_hora"] == retiro.origen["Ahora"]


def test_combinacion_no_greedy():
    billetes = svc.seleccionar_billetes(
        Decimal(60), [gaveta(1, 50, 1), gaveta(2, 20, 3)]
    )
    assert [(b.id_gaveta, b.cantidad) for b in billetes] == [(2, 3)]


def test_combinaciones_acotadas_contra_enumeracion_independiente():
    valores = (2, 3, 5)
    for existencias in product(range(3), repeat=3):
        disponibles = [
            gaveta(i + 1, v, n)
            for i, (v, n) in enumerate(zip(valores, existencias, strict=True))
        ]
        posibles = {
            sum(v * n for v, n in zip(valores, cantidades, strict=True))
            for cantidades in product(*(range(n + 1) for n in existencias))
        }
        # Solo multiplos de la minima configurada, como exige la HU.
        for monto in range(2, 22, 2):
            if monto not in posibles:
                with pytest.raises(HTTPException) as e:
                    svc.seleccionar_billetes(Decimal(monto), disponibles)
                assert e.value.status_code == 422
            else:
                seleccion = svc.seleccionar_billetes(Decimal(monto), disponibles)
                assert (
                    sum(valores[b.id_gaveta - 1] * b.cantidad for b in seleccion)
                    == monto
                )
                assert all(
                    0 < b.cantidad <= existencias[b.id_gaveta - 1] for b in seleccion
                )


@pytest.mark.parametrize(
    "gavetas",
    [
        [],
        [gaveta(1, 20, 1), gaveta(2, 10, 0)],
        [gaveta(1, 10, 10, Estado="I")],
        [gaveta(1, 10, 10, TipoPieza="Moneda")],
        [gaveta(1, 10, 10, EstadoDenominacion="I")],
    ],
)
def test_efectivo_insuficiente_no_se_reserva(gavetas):
    antes = deepcopy(gavetas)
    with pytest.raises(HTTPException) as e:
        svc.seleccionar_billetes(Decimal(30), gavetas)
    assert e.value.status_code == 422
    assert gavetas == antes


def test_total_suficiente_sin_combinacion():
    with pytest.raises(HTTPException) as e:
        svc.seleccionar_billetes(Decimal(30), [gaveta(1, 20, 4), gaveta(2, 10, 0)])
    assert e.value.status_code == 422


def test_multiplo_de_minima_configurada():
    with pytest.raises(HTTPException) as e:
        svc.seleccionar_billetes(Decimal(15), [gaveta(1, 10, 100)])
    assert e.value.status_code == 400


@pytest.mark.parametrize(
    "cambio",
    [
        {"CantidadActual": -1},
        {"CantidadActual": 1001},
        {"Valor": Decimal("NaN")},
        {"Valor": Decimal("0.001")},
        {"CantidadActual": True},
    ],
)
def test_configuracion_invalida_falla_cerrada(cambio):
    with pytest.raises(HTTPException) as e:
        svc.seleccionar_billetes(Decimal(30), [gaveta(1, 10, 10, **cambio)])
    assert e.value.status_code == 503


@pytest.mark.parametrize("codigo", ["05", "61", "65"])
def test_no_inventa_limites_ni_mapeos(retiro, codigo):
    retiro.autorizar.return_value = {"CodigoRespuesta": codigo, "Comision": 1}
    with pytest.raises(HTTPException) as e:
        preparar(retiro)
    assert e.value.status_code == 501


@pytest.mark.parametrize("codigo,saldo", [("51", 1000), ("00", 250)])
def test_fondos_incluyen_retenido_y_comision(retiro, codigo, saldo):
    retiro.origen["Saldo"] = saldo
    retiro.autorizar.return_value = {
        "CodigoRespuesta": codigo,
        "Comision": Decimal("1.25"),
    }
    with pytest.raises(HTTPException) as e:
        preparar(retiro)
    assert e.value.status_code == 422


@pytest.mark.parametrize("comision", [None, -1, Decimal("NaN")])
def test_no_presupone_comision_gratuita(retiro, comision):
    retiro.autorizar.return_value = {"CodigoRespuesta": "00", "Comision": comision}
    with pytest.raises(HTTPException) as e:
        preparar(retiro)
    assert e.value.status_code == 503


@pytest.mark.parametrize("caso", ["cuenta", "vinculo", "tarjeta", "terminal"])
def test_estado_y_autorizacion(retiro, monkeypatch, caso):
    if caso == "cuenta":
        retiro.origen["Estado"] = "Bloqueada"
    elif caso == "vinculo":
        retiro.tarjeta["id_cuenta"] = 2
    elif caso == "tarjeta":
        retiro.tarjeta["estado_tarjeta"] = "Generada"
    else:
        monkeypatch.setattr(svc.service, "validar_terminal", lambda *a: {"id_atm": 99})
    with pytest.raises(HTTPException):
        preparar(retiro)
    retiro.conn.begin.return_value.rollback.assert_called_once()
    retiro.autorizar.assert_not_called()


def anterior(p):
    return {
        "IdTransaccion": 70,
        "IdCuenta": 1,
        "IdTarjeta": 301,
        "IdATM": 10,
        "IdCanal": 1,
        "TipoOperacion": "Normal",
        "TipoTransaccion": "Retiro",
        "MTI": "0200",
        "Monto": p.entrada.monto,
    }


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("IdCuenta", 2),
        ("IdTarjeta", 302),
        ("IdATM", 11),
        ("IdCanal", 9),
        ("TipoOperacion", "Reverso"),
        ("TipoTransaccion", "Consulta"),
        ("MTI", "0400"),
        ("Monto", 1),
    ],
)
def test_registro_reutilizado(retiro, monkeypatch, campo, valor):
    monkeypatch.setattr(
        svc.repo, "leer_registro", lambda *a: {**anterior(retiro), campo: valor}
    )
    with pytest.raises(HTTPException) as e:
        preparar(retiro)
    assert e.value.status_code == 409


def test_registro_compatible_es_solo_candidato(retiro, monkeypatch):
    monkeypatch.setattr(svc.repo, "leer_registro", lambda *a: anterior(retiro))
    assert preparar(retiro).id_transaccion_candidata == 70


def test_error_sql_revierte_y_no_filtra(retiro):
    retiro.autorizar.side_effect = SQLAlchemyError("SQL_PRIVADO")
    with pytest.raises(HTTPException) as e:
        preparar(retiro)
    assert e.value.status_code == 503 and "SQL_PRIVADO" not in str(e.value.detail)
    retiro.conn.begin.return_value.rollback.assert_called_once()


def test_dependencias_ajenas_no_abren_barrera(retiro):
    with pytest.raises(HTTPException) as e:
        svc.solicitar_retiro(
            retiro.sesion, retiro.terminal, retiro.entrada, MagicMock()
        )
    assert e.value.status_code == 501
    retiro.conn.begin.assert_not_called()

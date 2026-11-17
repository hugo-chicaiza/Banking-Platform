from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text

from app.modules.contabilidad import repository
from app.modules.contabilidad.asientos import (
    ErrorContable,
    OperacionContable,
    generar_asiento,
)


@pytest.fixture
def operacion():
    return OperacionContable(
        codigo_plantilla="DEP_EFECTIVO_CAJA",
        clave_evento="TRANSACCION:1",
        id_agencia="001",
        id_fecha_contable=2,
        id_usuario=3,
        fecha_hora=datetime(2026, 11, 10, 12),
        importes={"MONTO": Decimal("100.00")},
        id_transaccion=1,
    )


@pytest.fixture
def contabilidad(monkeypatch):
    monkeypatch.setattr(repository, "buscar_asiento_evento", Mock(return_value=None))
    monkeypatch.setattr(
        repository,
        "obtener_plantilla",
        Mock(
            return_value={
                "IdPlantillaAsiento": 1,
                "IdConceptoContable": 1,
                "Origen": "CAJA",
                "IdTipoAsiento": 3,
                "Nombre": "Depósito",
                "Estado": True,
            }
        ),
    )
    monkeypatch.setattr(
        repository,
        "obtener_por_id",
        Mock(return_value={"fecha": date(2026, 11, 10), "es_dia_contable": True}),
    )
    monkeypatch.setattr(repository, "periodo_abierto", Mock(return_value=True))
    lineas = [
        {
            "IdCuentaContable": cuenta,
            "TipoMovimiento": lado,
            "ComponenteImporte": "MONTO",
            "Estado": True,
            "EsImputable": True,
        }
        for cuenta, lado in ((4, "DEBITO"), (16, "CREDITO"))
    ]
    monkeypatch.setattr(
        repository, "obtener_lineas_plantilla", Mock(return_value=lineas)
    )
    escrituras = {
        "insertar_asiento_automatico": Mock(return_value=10),
        "insertar_lineas_asiento": Mock(),
        "contabilizar_asiento": Mock(),
    }
    for nombre, doble in escrituras.items():
        monkeypatch.setattr(repository, nombre, doble)
    return lineas, escrituras


def test_generar_y_reintentar_evento(operacion, contabilidad, monkeypatch):
    _, escrituras = contabilidad
    with create_engine("sqlite://").begin() as conn:
        assert generar_asiento(conn, operacion) == 10
        cabecera = escrituras["insertar_asiento_automatico"].call_args.args[1]
        lineas = escrituras["insertar_lineas_asiento"].call_args.args[1]
        assert [(l["cuenta"], l["lado"], l["monto"]) for l in lineas] == [
            (4, "DEBITO", Decimal("100.00")),
            (16, "CREDITO", Decimal("100.00")),
        ]
        escrituras["contabilizar_asiento"].assert_called_once_with(conn, 10)
        monkeypatch.setattr(
            repository,
            "buscar_asiento_evento",
            Mock(
                return_value={
                    "IdAsientoContable": 10,
                    "HuellaEventoContable": cabecera["huella"],
                    "Estado": "CONTABILIZADO",
                }
            ),
        )
        assert generar_asiento(conn, operacion) == 10
        with pytest.raises(ErrorContable, match="otro asiento"):
            generar_asiento(conn, replace(operacion, importes={"MONTO": Decimal(200)}))
        escrituras["insertar_asiento_automatico"].assert_called_once()


@pytest.mark.parametrize("caso", ["descuadrado", "no imputable", "cerrado"])
def test_rechaza_configuracion_invalida(operacion, contabilidad, caso, monkeypatch):
    lineas, escrituras = contabilidad
    if caso == "descuadrado":
        lineas.pop()
    elif caso == "no imputable":
        lineas[0]["EsImputable"] = False
    else:
        monkeypatch.setattr(repository, "periodo_abierto", Mock(return_value=False))
    with create_engine("sqlite://").begin() as conn, pytest.raises(ErrorContable):
        generar_asiento(conn, operacion)
    escrituras["insertar_asiento_automatico"].assert_not_called()


def test_fallo_contable_revierte_operacion(operacion, contabilidad, monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE operacion (id int)"))
    monkeypatch.setattr(
        repository, "contabilizar_asiento", Mock(side_effect=RuntimeError)
    )
    with pytest.raises(RuntimeError), engine.begin() as conn:
        conn.execute(text("INSERT INTO operacion VALUES (1)"))
        generar_asiento(conn, operacion)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM operacion")).scalar_one() == 0

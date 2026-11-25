from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.clientes import habilitacion
from app.modules.cuentas import service as cuentas
from app.modules.cuentas.schemas import CuentaPendienteCreate

FECHA = date(2026, 11, 24)


def _cliente(**cambios):
    consulta = MagicMock()
    consulta.mappings.return_value.first.return_value = {
        "Estado": "Activo",
        "ConsentimientoDatos": True,
        "FechaConsentimiento": datetime(2026, 11, 23),
        "TipoCliente": "Natural",
        "ResultadoEvaluacion": "Aprobado",
        "EsPEP": False,
        "NivelRiesgoLAFT": "Bajo",
        "IdSolicitud": None,
        "AntecedenteImpeditivo": False,
        **cambios,
    }
    return consulta


def test_antecedente_impeditivo_bloquea_una_evaluacion_aprobada(monkeypatch):
    monkeypatch.setattr(habilitacion.general, "valor", lambda *_: False)
    conn = MagicMock()
    conn.execute.return_value = _cliente(AntecedenteImpeditivo=True)

    resultado = habilitacion.cliente_habilitado(conn, 3, FECHA)

    assert not resultado.habilitado
    assert "ANTECEDENTE_IMPIDE_VINCULACION" in resultado.motivos


def test_activacion_revalida_riesgo_y_no_cambia_la_cuenta_si_vencio(monkeypatch):
    monkeypatch.setattr(habilitacion.general, "valor", lambda *_: False)
    monkeypatch.setattr(cuentas, "hoy", lambda: FECHA)
    monkeypatch.setattr(
        cuentas.repository,
        "obtener_subproducto",
        lambda *_: {"estado_producto": "A", "estado_subproducto": "A"},
    )
    conn, cuenta = MagicMock(), MagicMock()
    cuenta.mappings.return_value.first.return_value = {
        "Estado": "PendienteDeposito",
        "IdCliente": 3,
        "IdSubProducto": 25,
        "MontoAperturaAplicado": Decimal(20),
    }
    conn.execute.side_effect = [cuenta, _cliente(ResultadoEvaluacion=None)]

    with pytest.raises(HTTPException) as error:
        cuentas.activar_si_corresponde(conn, 5, Decimal(20), 12)

    assert error.value.status_code == 409
    detalle = cast(dict[str, Any], error.value.detail)
    assert detalle["code"] == "CLIENTE_NO_HABILITADO"
    assert "RIESGO_NO_APROBADO_VIGENTE" in detalle["bloqueos"]
    assert conn.execute.call_count == 2


def test_requiere_estado_consentimiento_y_evaluacion(monkeypatch):
    monkeypatch.setattr(habilitacion.general, "valor", lambda *_: False)
    conn = MagicMock()
    conn.execute.return_value = _cliente(
        Estado="Pendiente", ConsentimientoDatos=False, ResultadoEvaluacion=None
    )
    resultado = habilitacion.cliente_habilitado(conn, 3, FECHA)
    assert not resultado.habilitado
    assert resultado.motivos == [
        "CLIENTE_NO_ACTIVO",
        "CONSENTIMIENTO_NO_VIGENTE",
        "RIESGO_NO_APROBADO_VIGENTE",
        "ARCHIVOS_NO_EXIGIDOS",
    ]


@pytest.mark.parametrize("aplicada", [False, True])
def test_pep_exige_comprobante_de_aprobacion(monkeypatch, aplicada):
    monkeypatch.setattr(habilitacion.general, "valor", lambda *_: False)
    conn, comprobante = MagicMock(), MagicMock()
    comprobante.first.return_value = (1,) if aplicada else None
    conn.execute.side_effect = [_cliente(EsPEP=True, IdSolicitud=12), comprobante]
    assert habilitacion.cliente_habilitado(conn, 3, FECHA).habilitado is aplicada
    assert conn.execute.call_args.args[1] == {"solicitud": 12}


@pytest.mark.parametrize("faltantes", [[], ["IDENTIDAD"]])
def test_archivos_activos_exigen_evidencia_limpia(monkeypatch, faltantes):
    monkeypatch.setattr(habilitacion.general, "valor", lambda *_: True)
    conn, catalogo, archivos = MagicMock(), MagicMock(), MagicMock()
    catalogo.scalar_one.return_value = 1
    archivos.scalars.return_value = faltantes
    conn.execute.side_effect = [_cliente(), catalogo, archivos]
    resultado = habilitacion.cliente_habilitado(conn, 3, FECHA)
    assert resultado.habilitado is (not faltantes)
    assert resultado.motivos == [f"ARCHIVO_OBLIGATORIO_FALTANTE:{c}" for c in faltantes]


def test_archivos_activos_sin_catalogo_fallan_cerrado(monkeypatch):
    monkeypatch.setattr(habilitacion.general, "valor", lambda *_: True)
    conn, catalogo = MagicMock(), MagicMock()
    catalogo.scalar_one.return_value = 0
    conn.execute.side_effect = [_cliente(), catalogo]
    with pytest.raises(HTTPException) as exc:
        habilitacion.cliente_habilitado(conn, 3, FECHA)
    assert exc.value.status_code == 503


def test_apertura_sin_comprobante_de_aprobacion_no_reserva_numero(monkeypatch):
    monkeypatch.setattr(habilitacion.general, "valor", lambda *_: False)
    monkeypatch.setattr(cuentas, "hoy", lambda: FECHA)
    monkeypatch.setattr(
        cuentas.clientes_repository, "bloquear_cliente", lambda *_: {"estado": "Activo"}
    )
    reservar = MagicMock()
    monkeypatch.setattr(cuentas, "siguiente_numero_cuenta", reservar)
    conn, comprobante = MagicMock(), MagicMock()
    comprobante.first.return_value = None
    conn.execute.side_effect = [_cliente(EsPEP=True, IdSolicitud=12), comprobante]
    with pytest.raises(HTTPException) as exc:
        cuentas.abrir_cuenta_pendiente(
            conn,
            CuentaPendienteCreate.model_validate({"idCliente": 3, "idSubProducto": 25}),
            "001",
            1,
        )
    assert exc.value.status_code == 409
    detalle = cast(dict[str, Any], exc.value.detail)
    assert detalle["code"] == "CLIENTE_NO_HABILITADO"
    assert detalle["bloqueos"][0] == "RIESGO_NO_APROBADO_VIGENTE"
    reservar.assert_not_called()
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()

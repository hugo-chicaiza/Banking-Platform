from datetime import date, datetime
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
        **cambios,
    }
    return consulta


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
    detalle = exc.value.detail
    assert isinstance(detalle, dict)
    assert detalle["code"] == "CLIENTE_NO_HABILITADO"
    assert detalle["bloqueos"][0] == "RIESGO_NO_APROBADO_VIGENTE"
    reservar.assert_not_called()
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()

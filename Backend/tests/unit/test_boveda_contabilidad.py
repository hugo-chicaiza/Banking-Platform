"""Configuración contable y validación de los participantes de BOV."""

from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.auth import service as auth
from app.modules.contabilidad import service as contabilidad


@pytest.fixture
def configuracion(monkeypatch):
    repo = contabilidad.repository
    mocks = {}
    for nombre, resultado in {
        "periodo_boveda": {"fecha": datetime(2026, 11, 16).date(), "estado": "ABIERTO"},
        "plantilla_boveda": {
            "debito": 2,
            "credito": 3,
            "tipo_asiento": 1,
            "estado_tipo": "A",
        },
        "cuenta_boveda": {"estado": True, "imputable": True, "naturaleza": "DEUDORA"},
        "crear_asiento_boveda": 99,
        "linea_boveda": None,
        "confirmar_asiento_boveda": None,
    }.items():
        mocks[nombre] = MagicMock(return_value=resultado)
        monkeypatch.setattr(repo, nombre, mocks[nombre])
    return mocks


def contabilizar(conn):
    return contabilidad.contabilizar_boveda(
        conn,
        agencia="001",
        tipo="ProvisionExterna",
        naturaleza="I",
        monto=Decimal("20.00"),
        fecha_contable=5,
        actor=7,
        movimiento=15,
        ahora=datetime(2026, 11, 16),
    )


def test_asiento_boveda_cuadra_y_comparte_la_conexion(configuracion):
    conn = MagicMock()
    assert contabilizar(conn) == 99
    lineas = configuracion["linea_boveda"].call_args_list
    assert len(lineas) == 2
    assert lineas[0].args[:6] == (conn, 99, 2, "001", Decimal(20), "DEBITO")
    assert lineas[1].args[:6] == (conn, 99, 3, "001", Decimal(20), "CREDITO")
    configuracion["confirmar_asiento_boveda"].assert_called_once_with(conn, 99)


@pytest.mark.parametrize(
    "funcion,resultado,code",
    [
        ("periodo_boveda", None, "PERIODO_CONTABLE_NO_ABIERTO"),
        ("periodo_boveda", {"estado": "CERRADO"}, "PERIODO_CONTABLE_NO_ABIERTO"),
        ("plantilla_boveda", None, "PLANTILLA_BOVEDA_NO_CONFIGURADA"),
        ("plantilla_boveda", {"estado_tipo": "I"}, "PLANTILLA_BOVEDA_NO_CONFIGURADA"),
        ("cuenta_boveda", None, "CUENTA_CONTABLE_NO_HABILITADA"),
        (
            "cuenta_boveda",
            {"estado": False, "imputable": True},
            "CUENTA_CONTABLE_NO_HABILITADA",
        ),
        (
            "cuenta_boveda",
            {"estado": True, "imputable": False},
            "CUENTA_CONTABLE_NO_HABILITADA",
        ),
    ],
)
def test_contabilidad_rechaza_configuracion_incompleta(
    configuracion, funcion, resultado, code
):
    configuracion[funcion].return_value = resultado
    with pytest.raises(HTTPException) as error:
        contabilizar(MagicMock())
    detalle = cast(dict[str, Any], error.value.detail)
    assert isinstance(detalle, dict)
    assert detalle["code"] == code
    configuracion["crear_asiento_boveda"].assert_not_called()


def test_contabilizar_exige_transaccion_abierta(configuracion):
    conn = MagicMock()
    conn.in_transaction.return_value = False
    with pytest.raises(RuntimeError, match="requiere una transacción"):
        contabilizar(conn)
    configuracion["periodo_boveda"].assert_not_called()


@pytest.fixture
def participante(monkeypatch):
    monkeypatch.setattr(auth, "get_engine", MagicMock())
    obtener = MagicMock(
        return_value={
            "Estado": "Activo",
            "KeyUsuario": "user_testigo",
            "RolesWorkOS": "org-supervisor",
            "AgenciaID": "001",
        }
    )
    monkeypatch.setattr(auth.repository, "obtener_usuario", obtener)
    bloqueo = MagicMock(return_value=None)
    monkeypatch.setattr(auth.repository, "bloqueo_vigente", bloqueo)
    return obtener, bloqueo


def test_participante_vigente_misma_agencia_y_rol(participante):
    auth.validar_participante_boveda(9, "001", frozenset({"SUPERVISOR"}))


@pytest.mark.parametrize(
    "campo,valor,code",
    [
        ("Estado", "Inactivo", "PARTICIPANTE_NO_HABILITADO"),
        ("KeyUsuario", None, "PARTICIPANTE_NO_HABILITADO"),
        ("RolesWorkOS", "org-cajero", "PARTICIPANTE_NO_HABILITADO"),
        ("AgenciaID", "002", "SIN_ACCESO_AGENCIA"),
    ],
)
def test_participante_inhabilitado_o_fuera_de_alcance(participante, campo, valor, code):
    obtener, _ = participante
    obtener.return_value = {**obtener.return_value, campo: valor}
    with pytest.raises(HTTPException) as error:
        auth.validar_participante_boveda(9, "001", frozenset({"SUPERVISOR"}))
    detalle = cast(dict[str, Any], error.value.detail)
    assert isinstance(detalle, dict)
    assert detalle["code"] == code


def test_testigo_auditor_puede_observar_otra_agencia(participante):
    obtener, _ = participante
    obtener.return_value = {
        **obtener.return_value,
        "RolesWorkOS": "org-auditor",
        "AgenciaID": "002",
    }
    auth.validar_participante_boveda(9, "001", frozenset({"AUDITOR", "SUPERVISOR"}))


def test_participante_bloqueado_no_autoriza(participante):
    _, bloqueo = participante
    bloqueo.return_value = {"BloqueoID": 1}
    with pytest.raises(HTTPException):
        auth.validar_participante_boveda(9, "001", frozenset({"SUPERVISOR"}))


def test_autorizador_con_rol_auditor_adicional_no_elude_agencia(participante):
    obtener, _ = participante
    obtener.return_value = {
        **obtener.return_value,
        "RolesWorkOS": "org-supervisor,org-auditor",
        "AgenciaID": "002",
    }
    with pytest.raises(HTTPException) as error:
        auth.validar_participante_boveda(9, "001", frozenset({"SUPERVISOR"}))
    detalle = cast(dict[str, Any], error.value.detail)
    assert isinstance(detalle, dict)
    assert detalle["code"] == "SIN_ACCESO_AGENCIA"


def test_participante_inexistente_no_autoriza(participante):
    obtener, _ = participante
    obtener.return_value = None
    with pytest.raises(HTTPException) as error:
        auth.validar_participante_boveda(9, "001", frozenset({"SUPERVISOR"}))
    detalle = cast(dict[str, Any], error.value.detail)
    assert isinstance(detalle, dict)
    assert detalle["code"] == "PARTICIPANTE_NO_HABILITADO"

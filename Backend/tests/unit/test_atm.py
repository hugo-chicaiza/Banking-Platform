from datetime import date, timedelta
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.atm import service
from app.modules.atm.service import validar_terminal


def atm_valido():
    return {
        "id_atm": 1,
        "codigo_atm": "ATM00001",
        "tipo_terminal": "ATM",
        "estado_atm": "A",
        "estado_canal": "A",
        "requiere_tarjeta": True,
        "requiere_pin": True,
        "requiere_terminal": True,
    }


def test_atm_activo():
    with patch(
        "app.modules.atm.service.repository.obtener_atm",
        return_value=atm_valido(),
    ):
        resultado = validar_terminal(MagicMock(), "ATM00001")

    assert resultado["id_atm"] == 1


@pytest.mark.parametrize(
    "campo, valor",
    [
        ("estado_atm", "I"),
        ("estado_atm", "M"),
        ("estado_canal", "I"),
        ("tipo_terminal", "POS"),
        ("requiere_tarjeta", False),
        ("requiere_pin", False),
        ("requiere_terminal", False),
    ],
)
def test_atm_no_disponible(campo, valor):
    datos = atm_valido()
    datos[campo] = valor

    with (
        patch(
            "app.modules.atm.service.repository.obtener_atm",
            return_value=datos,
        ),
        pytest.raises(HTTPException) as error,
    ):
        validar_terminal(MagicMock(), "ATM00001")

    assert error.value.status_code == 409


def test_atm_inexistente():
    with (
        patch(
            "app.modules.atm.service.repository.obtener_atm",
            return_value=None,
        ),
        pytest.raises(HTTPException) as error,
    ):
        validar_terminal(MagicMock(), "ATM99999")

    assert error.value.status_code == 409


def test_validar_tarjeta_activa():
    tarjeta = {
        "id_tarjeta": 1,
        "estado_tarjeta": "Activa",
        "fecha_expiracion": date.today() + timedelta(days=30),
        "pin_asignado": True,
    }

    with patch(
        "app.modules.atm.service.repository.obtener_tarjeta",
        return_value=tarjeta,
    ):
        resultado = service.validar_tarjeta(MagicMock(), 1)

    assert resultado == tarjeta


@pytest.mark.parametrize(
    (
        "estado",
        "pin_asignado",
        "dias_vigencia",
        "codigo_esperado",
        "http_esperado",
    ),
    [
        ("Bloqueada", True, 30, "TARJETA_BLOQUEADA", 423),
        ("Vencida", True, -1, "TARJETA_NO_ACTIVA", 409),
        ("Activa", True, -1, "TARJETA_NO_ACTIVA", 409),
        ("Activa", False, 30, "PIN_NO_CONFIGURADO", 409),
    ],
)
def test_validar_tarjeta_rechazada(
    estado,
    pin_asignado,
    dias_vigencia,
    codigo_esperado,
    http_esperado,
):
    tarjeta = {
        "estado_tarjeta": estado,
        "fecha_expiracion": date.today() + timedelta(days=dias_vigencia),
        "pin_asignado": pin_asignado,
    }

    with (
        patch(
            "app.modules.atm.service.repository.obtener_tarjeta",
            return_value=tarjeta,
        ),
        pytest.raises(HTTPException) as error,
    ):
        service.validar_tarjeta(MagicMock(), 1)

    assert error.value.status_code == http_esperado
    detalle = cast(dict[str, Any], error.value.detail)
    assert detalle["code"] == codigo_esperado


def test_validar_tarjeta_inexistente():
    with (
        patch(
            "app.modules.atm.service.repository.obtener_tarjeta",
            return_value=None,
        ),
        pytest.raises(HTTPException) as error,
    ):
        service.validar_tarjeta(MagicMock(), 999)

    assert error.value.status_code == 409


def test_validar_estado_pin_activo():
    estado_pin = {
        "id_tarjeta": 1,
        "tiene_pin_asignado": True,
        "intentos_fallidos": 0,
        "estado_pin": "Activo",
        "fecha_bloqueo": None,
        "pin_offset": "1234",
        "referencia_clave_pvk": "SIM-PVK-01",
    }

    with patch(
        "app.modules.atm.service.repository.obtener_estado_pin",
        return_value=estado_pin,
    ):
        resultado = service.validar_estado_pin(MagicMock(), 1)

    assert resultado == estado_pin


@pytest.mark.parametrize(
    (
        "tiene_pin",
        "estado",
        "codigo_esperado",
        "http_esperado",
    ),
    [
        (False, "Activo", "PIN_NO_CONFIGURADO", 409),
        (True, "Bloqueado", "PIN_BLOQUEADO", 423),
        (True, "Inactivo", "PIN_NO_DISPONIBLE", 409),
    ],
)
def test_validar_estado_pin_rechazado(
    tiene_pin,
    estado,
    codigo_esperado,
    http_esperado,
):
    estado_pin = {
        "tiene_pin_asignado": tiene_pin,
        "estado_pin": estado,
        "intentos_fallidos": 0,
        "pin_offset": "1234",
        "referencia_clave_pvk": "SIM-PVK-01",
    }

    with (
        patch(
            "app.modules.atm.service.repository.obtener_estado_pin",
            return_value=estado_pin,
        ),
        pytest.raises(HTTPException) as error,
    ):
        service.validar_estado_pin(MagicMock(), 1)

    assert error.value.status_code == http_esperado
    detalle = cast(dict[str, Any], error.value.detail)
    assert detalle["code"] == codigo_esperado


def test_validar_estado_pin_inexistente():
    with (
        patch(
            "app.modules.atm.service.repository.obtener_estado_pin",
            return_value=None,
        ),
        pytest.raises(HTTPException) as error,
    ):
        service.validar_estado_pin(MagicMock(), 999)

    assert error.value.status_code == 409
    detalle = cast(dict[str, Any], error.value.detail)
    assert detalle["code"] == "PIN_NO_DISPONIBLE"


# A-05: tarjeta Generada


def _generada(tipo: str | None) -> dict:
    return {
        "id_tarjeta": 1,
        "estado_tarjeta": "Generada",
        "tipo_tarjeta": tipo,
        "fecha_emision": date.today() - timedelta(days=7),
        "fecha_expiracion": date.today() + timedelta(days=30),
        "pin_asignado": True,
    }


def test_debito_generada_se_acepta_para_el_primer_cambio_de_pin():
    tarjeta = _generada("Debito")
    with patch(
        "app.modules.atm.service.repository.obtener_tarjeta", return_value=tarjeta
    ):
        assert service.validar_tarjeta(MagicMock(), 1) == tarjeta


@pytest.mark.parametrize(("dias", "aceptada"), [(3, True), (4, True), (2, False)])
def test_credito_generada_solo_tras_tres_dias_laborables(monkeypatch, dias, aceptada):
    tarjeta = _generada("Credito")
    consultas = []

    def laborables(_conn, fecha):
        consultas.append(fecha)
        return dias

    monkeypatch.setattr(
        "app.modules.tarjetas.repository.dias_laborables_desde", laborables
    )
    with patch(
        "app.modules.atm.service.repository.obtener_tarjeta", return_value=tarjeta
    ):
        if aceptada:
            assert service.validar_tarjeta(MagicMock(), 1) == tarjeta
        else:
            with pytest.raises(HTTPException) as error:
                service.validar_tarjeta(MagicMock(), 1)
            assert error.value.status_code == 409
    assert consultas == [tarjeta["fecha_emision"]]


@pytest.mark.parametrize("estado", ["Solicitada", "Aprobada"])
def test_tarjeta_sin_generar_no_opera(estado):
    tarjeta = {**_generada("Debito"), "estado_tarjeta": estado}
    with (
        patch(
            "app.modules.atm.service.repository.obtener_tarjeta", return_value=tarjeta
        ),
        pytest.raises(HTTPException) as error,
    ):
        service.validar_tarjeta(MagicMock(), 1)
    assert cast(dict[str, Any], error.value.detail)["code"] == "TARJETA_NO_ACTIVA"


def test_generada_sin_tipo_conocido_no_opera():
    with (
        patch(
            "app.modules.atm.service.repository.obtener_tarjeta",
            return_value=_generada(None),
        ),
        pytest.raises(HTTPException) as error,
    ):
        service.validar_tarjeta(MagicMock(), 1)
    assert error.value.status_code == 409


@pytest.mark.parametrize("nocount", [False, True])
@pytest.mark.parametrize("activadas", [0, 1])
def test_activar_credito_sql_idempotente_con_historial(nocount, activadas):
    from app.modules.atm import repository

    conn = MagicMock()
    cursor = conn.connection.cursor.return_value
    # Con NOCOUNT OFF hay contadores sin columnas antes del SELECT final.
    descripciones = ([] if nocount else [None, None]) + [[("Activadas",)]]
    cursor.description = descripciones[0]
    cursor.fetchall.return_value = [(activadas,)]
    pendientes = iter(descripciones[1:])

    def nextset():
        try:
            cursor.description = next(pendientes)
            return True
        except StopIteration:
            return False

    cursor.nextset.side_effect = nextset
    repository.activar_tarjeta_credito(conn, 301, 4, 900, "10.0.0.1")
    cursor.execute.assert_called_once()
    batch, params = cursor.execute.call_args.args
    assert "Estado = 'Generada'" in str(batch) and "'Credito'" in str(batch)
    assert "OUTPUT INSERTED.IdTarjeta INTO @activadas" in str(batch)
    assert "FROM @activadas" in str(batch)
    assert "'Activacion'" in str(batch)
    assert "SET NOCOUNT" not in str(batch)
    assert params == (301, 4, 900, "10.0.0.1")
    assert cursor.nextset.call_count == len(descripciones)
    cursor.close.assert_called_once()
    conn.execute.assert_not_called()

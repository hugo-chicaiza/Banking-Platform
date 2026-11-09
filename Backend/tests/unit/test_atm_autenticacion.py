import hashlib
from datetime import date, timedelta
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.core.security.hsm import (
    ClaveNoAutorizada,
    ErrorHsm,
    HsmNoDisponible,
    HsmSimulado,
    PinBlockInvalido,
)
from app.modules.atm import repository, service
from app.modules.tarjetas import repository as tarjetas_repository
from app.modules.tarjetas.service import pan_de_prueba
from tests.pin_version import FECHA_PIN, VERSION_PIN


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def sin_conexiones_reales(monkeypatch):
    def prohibido(*args, **kwargs):
        raise AssertionError("Las pruebas ATM no pueden crear conexiones reales")

    monkeypatch.setattr("pyodbc.connect", prohibido)
    monkeypatch.setattr("sqlalchemy.create_engine", prohibido)
    monkeypatch.setattr("app.core.database.db.create_engine", prohibido)


@pytest.fixture
def entorno_atm(monkeypatch):
    e = MagicMock()
    e.pan = "5000001234567896"
    e.estado = {
        "tiene_pin_asignado": True,
        "estado_pin": "Activo",
        "intentos_fallidos": 0,
        "fecha_asignacion": FECHA_PIN,
        "pin_offset": "1234",
        "referencia_clave_pvk": "SIM-PVK-01",
    }
    e.tarjeta = {
        "estado_tarjeta": "Activa",
        "pin_asignado": True,
        "fecha_expiracion": date.today() + timedelta(days=30),
        "hash_numero_tarjeta": hashlib.sha256(e.pan.encode()).digest(),
    }
    e.leer_tarjeta.return_value = e.tarjeta
    e.leer_pin.return_value = e.estado
    e.resultado.return_value = {"intentos_fallidos": 0, "estado_pin": "Activo"}
    e.leer_pan.return_value = e.pan
    e.factory.return_value = e.hsm
    e.hsm.verificar_pin.return_value = True
    e.engine.begin.return_value.__enter__.return_value = e.conn_pin
    e.engine.begin.return_value.__exit__.return_value = False
    monkeypatch.setattr(service, "get_engine", lambda _db: e.engine)
    monkeypatch.setattr(service, "obtener_hsm", e.factory)
    monkeypatch.setattr(service, "pan_de_prueba", e.leer_pan)
    monkeypatch.setattr(repository, "obtener_tarjeta", e.leer_tarjeta)
    monkeypatch.setattr(repository, "obtener_pin_para_verificacion", e.leer_pin)
    monkeypatch.setattr(repository, "guardar_resultado_pin", e.resultado)
    return e


async def autenticar(e):
    return await service.autenticar_pin_ficticio_atm(
        e.conn, 1, "00" * 16, "TEST-KEY-01"
    )


def comprobar_error(error, status, code):
    assert error.value.status_code == status
    assert cast(dict[str, Any], error.value.detail)["code"] == code


@pytest.mark.anyio
async def test_pin_correcto_utiliza_contrato_compartido(entorno_atm):
    e = entorno_atm
    assert await autenticar(e) == service.PinVerificado(
        requiere_cambio=False, pin_version=VERSION_PIN
    )
    e.factory.assert_called_once_with()
    e.leer_pin.assert_called_once_with(e.conn_pin, 1)
    e.leer_pan.assert_called_once_with(e.conn_pin, 1, e.hsm)
    e.hsm.verificar_pin.assert_called_once_with(
        "00" * 16, "TEST-KEY-01", e.pan, "1234", "SIM-PVK-01"
    )
    e.resultado.assert_called_once_with(
        conn=e.conn_pin, id_tarjeta=1, pin_correcto=True
    )
    e.engine.begin.return_value.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.anyio
async def test_version_se_captura_antes_de_confirmar_y_no_se_relee(entorno_atm):
    e = entorno_atm

    def guardar(**_kwargs):
        e.estado["fecha_asignacion"] = FECHA_PIN.replace(day=2)
        return {"intentos_fallidos": 0, "estado_pin": "Activo"}

    e.resultado.side_effect = guardar
    verified = await autenticar(e)
    assert verified.pin_version == VERSION_PIN
    e.leer_pin.assert_called_once()


@pytest.mark.anyio
@pytest.mark.parametrize("fecha", [None, "2026-11-01"])
async def test_fecha_asignacion_invalida_no_consume_intentos(entorno_atm, fecha):
    e = entorno_atm
    e.estado["fecha_asignacion"] = fecha
    with pytest.raises(HTTPException) as exc:
        await autenticar(e)
    assert exc.value.status_code == 503
    e.resultado.assert_not_called()
    e.hsm.verificar_pin.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "intentos,estado,status,code",
    [
        (1, "Activo", 401, "PIN_INCORRECTO"),
        (2, "Activo", 401, "PIN_INCORRECTO"),
        (3, "Bloqueado", 423, "PIN_BLOQUEADO"),
    ],
)
async def test_intentos_se_confirman_antes_del_error(
    entorno_atm, intentos, estado, status, code
):
    e = entorno_atm
    e.hsm.verificar_pin.return_value = False
    e.resultado.return_value = {"intentos_fallidos": intentos, "estado_pin": estado}
    with pytest.raises(HTTPException) as error:
        await autenticar(e)
    comprobar_error(error, status, code)
    e.resultado.assert_called_once_with(
        conn=e.conn_pin, id_tarjeta=1, pin_correcto=False
    )
    e.engine.begin.return_value.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "cambios,code,status",
    [
        ({"estado_pin": "Bloqueado", "intentos_fallidos": 3}, "PIN_BLOQUEADO", 423),
        (
            {"tiene_pin_asignado": False, "estado_pin": "Inactivo"},
            "PIN_NO_CONFIGURADO",
            409,
        ),
        ({"estado_pin": "Inactivo"}, "PIN_NO_DISPONIBLE", 409),
        ({"pin_offset": None}, "PIN_NO_DISPONIBLE", 409),
        ({"referencia_clave_pvk": None}, "PIN_NO_DISPONIBLE", 409),
    ],
)
async def test_estado_no_operable_no_verifica_ni_cuenta(
    entorno_atm, cambios, code, status
):
    e = entorno_atm
    e.estado.update(cambios)
    with pytest.raises(HTTPException) as error:
        await autenticar(e)
    comprobar_error(error, status, code)
    e.hsm.verificar_pin.assert_not_called()
    e.resultado.assert_not_called()
    e.leer_pan.assert_not_called()


@pytest.mark.anyio
async def test_fila_pin_ausente(entorno_atm):
    e = entorno_atm
    e.leer_pin.return_value = None
    with pytest.raises(HTTPException) as error:
        await autenticar(e)
    comprobar_error(error, 409, "PIN_NO_DISPONIBLE")
    e.resultado.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "excepcion,status,code",
    [
        (PinBlockInvalido("detalle privado"), 422, "PIN_BLOCK_INVALIDO"),
        (ClaveNoAutorizada("detalle privado"), 422, "CLAVE_NO_AUTORIZADA"),
        (HsmNoDisponible("detalle privado"), 503, "HSM_NO_DISPONIBLE"),
        (ErrorHsm("detalle privado"), 503, "HSM_NO_DISPONIBLE"),
    ],
)
async def test_errores_hsm_no_consumen_intentos(entorno_atm, excepcion, status, code):
    e = entorno_atm
    e.hsm.verificar_pin.side_effect = excepcion
    with pytest.raises(HTTPException) as error:
        await autenticar(e)
    comprobar_error(error, status, code)
    assert "detalle privado" not in str(error.value.detail)
    e.resultado.assert_not_called()
    assert e.engine.begin.return_value.__exit__.call_args.args[0] is HTTPException


@pytest.mark.anyio
async def test_hsm_no_configurado(entorno_atm):
    e = entorno_atm
    e.factory.side_effect = HsmNoDisponible()
    with pytest.raises(HTTPException) as error:
        await autenticar(e)
    comprobar_error(error, 503, "HSM_NO_DISPONIBLE")
    e.engine.begin.assert_not_called()
    e.resultado.assert_not_called()


@pytest.mark.anyio
async def test_pan_no_disponible_no_cuenta(entorno_atm):
    e = entorno_atm
    e.leer_pan.side_effect = service.problema(503, "PAN_NO_DISPONIBLE", "Sin PAN")
    with pytest.raises(HTTPException) as error:
        await autenticar(e)
    comprobar_error(error, 503, "PAN_NO_DISPONIBLE")
    e.resultado.assert_not_called()
    e.hsm.verificar_pin.assert_not_called()


@pytest.mark.anyio
async def test_pan_no_corresponde_a_tarjeta(entorno_atm):
    e = entorno_atm
    e.tarjeta["hash_numero_tarjeta"] = bytes(32)
    with pytest.raises(HTTPException) as error:
        await autenticar(e)
    comprobar_error(error, 409, "TARJETA_NO_DISPONIBLE")
    e.resultado.assert_not_called()
    e.hsm.verificar_pin.assert_not_called()


@pytest.mark.anyio
async def test_actualizacion_rechazada(entorno_atm):
    e = entorno_atm
    e.resultado.return_value = None
    with pytest.raises(HTTPException) as error:
        await autenticar(e)
    comprobar_error(error, 423, "PIN_BLOQUEADO")


@pytest.mark.anyio
async def test_fallo_persistencia_revierte_transaccion(entorno_atm):
    e = entorno_atm
    e.resultado.side_effect = RuntimeError("fallo simulado")
    with pytest.raises(RuntimeError, match="fallo simulado"):
        await autenticar(e)
    assert e.engine.begin.return_value.__exit__.call_args.args[0] is RuntimeError


@pytest.mark.parametrize(
    "consulta,bloquea",
    [
        (repository.obtener_estado_pin, False),
        (repository.obtener_pin_para_verificacion, True),
    ],
)
def test_consulta_offset_y_pvk_con_mock(consulta, bloquea):
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "fecha_asignacion": FECHA_PIN,
        "pin_offset": "1234",
        "referencia_clave_pvk": "SIM-PVK-01",
    }
    assert consulta(conn, 1)["referencia_clave_pvk"] == "SIM-PVK-01"
    sql, params = conn.execute.call_args.args
    assert "PINOffset AS pin_offset" in str(sql)
    assert "ReferenciaClavePVK AS referencia_clave_pvk" in str(sql)
    assert ("UPDLOCK, ROWLOCK" in str(sql)) is bloquea
    assert params == {"id_tarjeta": 1}


@pytest.mark.parametrize("correcto", [True, False])
def test_actualizacion_sql_intentos_con_mock(correcto):
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "estado_pin": "Activo"
    }
    repository.guardar_resultado_pin(conn, 1, correcto)
    sql = str(conn.execute.call_args.args[0])
    assert "Estado = 'Activo'" in sql
    assert "TienePINAsignado = 1" in sql
    assert "IntentosFallidos < 3" in sql
    if correcto:
        assert "SET IntentosFallidos = 0" in sql
    else:
        assert "IntentosFallidos + 1 >= 3" in sql
        assert "IntentosFallidos < 3" in sql


def test_pan_compartido_descifra_con_id_y_referencia(monkeypatch):
    conn, hsm = MagicMock(), MagicMock()
    leer = MagicMock(return_value=(b"cifrado ficticio", "SIM-PAN-01"))
    monkeypatch.setattr(tarjetas_repository, "obtener_pan_ficticio", leer)
    hsm.descifrar_pan.return_value = "5000001234567896"
    assert pan_de_prueba(conn, 1, hsm) == hsm.descifrar_pan.return_value
    hsm.descifrar_pan.assert_called_once_with(b"cifrado ficticio", "SIM-PAN-01", 1)


@pytest.mark.parametrize("guardado", [None, (b"cifrado ficticio", "SIM-PAN-01")])
def test_pan_compartido_traduce_ausencia_o_error(monkeypatch, guardado):
    monkeypatch.setattr(
        tarjetas_repository, "obtener_pan_ficticio", MagicMock(return_value=guardado)
    )
    hsm = MagicMock()
    hsm.descifrar_pan.side_effect = HsmNoDisponible()
    with pytest.raises(HTTPException) as error:
        pan_de_prueba(MagicMock(), 1, hsm)
    comprobar_error(error, 503, "PAN_NO_DISPONIBLE")


def test_repositorio_pan_compartido_con_mock():
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value = [
        {
            "cifrado": b"ficticio",
            "referencia": "SIM-PAN-01",
        }
    ]
    assert tarjetas_repository.obtener_pan_ficticio(conn, 1) == (
        b"ficticio",
        "SIM-PAN-01",
    )
    conn.execute.return_value.mappings.return_value = []
    assert tarjetas_repository.obtener_pan_ficticio(conn, 1) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "offset",
    [
        None,
        "",
        "123",
        "12345",
        "12X4",
        " 123",
        "1234\n",
        "１２３４",
        "١٢٣٤",
        1234,
        b"1234",
    ],
)
async def test_offset_invalido_rechaza_sin_hsm_ni_intentos(entorno_atm, offset):
    e = entorno_atm
    e.estado.update(pin_offset=offset, intentos_fallidos=2)
    estado_previo = e.estado.copy()
    with pytest.raises(HTTPException) as error:
        await autenticar(e)
    comprobar_error(error, 409, "PIN_NO_DISPONIBLE")
    assert cast(dict[str, Any], error.value.detail)["message"] == (
        "No se puede utilizar el PIN de esta tarjeta."
    )
    e.hsm.verificar_pin.assert_not_called()
    e.leer_pan.assert_not_called()
    e.resultado.assert_not_called()
    assert e.estado == estado_previo
    assert e.engine.begin.return_value.__exit__.call_args.args[0] is HTTPException


@pytest.mark.anyio
@pytest.mark.parametrize("intentos", [3, 4, 99])
async def test_activo_con_limite_agotado_no_reinicia_contador(entorno_atm, intentos):
    e = entorno_atm
    e.estado.update(estado_pin="Activo", intentos_fallidos=intentos)
    # Aunque el HSM respondería True, el estado debe rechazarse antes de verificar.
    e.hsm.verificar_pin.return_value = True
    with pytest.raises(HTTPException) as error:
        await autenticar(e)
    comprobar_error(error, 423, "PIN_BLOQUEADO")
    e.hsm.verificar_pin.assert_not_called()
    e.leer_pan.assert_not_called()
    e.resultado.assert_not_called()
    assert e.estado["intentos_fallidos"] == intentos


@pytest.mark.anyio
async def test_offset_cero_y_dos_intentos_siguen_permitiendo_pin_correcto(entorno_atm):
    e = entorno_atm
    e.estado.update(pin_offset="0000", intentos_fallidos=2)
    assert await autenticar(e) == service.PinVerificado(
        requiere_cambio=False, pin_version=VERSION_PIN
    )
    assert e.hsm.verificar_pin.call_args.args[3] == "0000"
    e.resultado.assert_called_once_with(
        conn=e.conn_pin, id_tarjeta=1, pin_correcto=True
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fallo,status,code",
    [
        ("bloque", 422, "PIN_BLOCK_INVALIDO"),
        ("referencia", 422, "CLAVE_NO_AUTORIZADA"),
        ("pvk", 503, "HSM_NO_DISPONIBLE"),
    ],
)
async def test_errores_del_hsm_real_no_consumen_intentos(
    entorno_atm, fallo, status, code
):
    e = entorno_atm
    hsm = HsmSimulado(
        clave_pan=bytes(range(32)),
        clave_pvk=bytes(range(100, 116)),
        claves_pin_block={"TEST-KEY-01": bytes(range(32, 64))},
        referencia_pin_block="TEST-KEY-01",
    )
    e.factory.return_value = hsm
    e.estado["intentos_fallidos"] = 2
    bloque, referencia = hsm.construir_pin_block("7392", e.pan)
    if fallo == "bloque":
        bloque = "Z" * 32
    elif fallo == "referencia":
        referencia = "NO-AUTORIZADA"
    else:
        e.estado["referencia_clave_pvk"] = "OTRA-PVK"
    with pytest.raises(HTTPException) as error:
        await service.autenticar_pin_ficticio_atm(e.conn, 1, bloque, referencia)
    comprobar_error(error, status, code)
    e.resultado.assert_not_called()
    assert e.estado["intentos_fallidos"] == 2
    assert bloque not in str(error.value.detail)


@pytest.mark.anyio
@pytest.mark.parametrize("pin_ingresado,correcto", [("7392", True), ("4826", False)])
async def test_atm_verifica_offset_generado_por_hsm_real(
    entorno_atm, pin_ingresado, correcto
):
    e = entorno_atm
    hsm = HsmSimulado(
        clave_pan=bytes(range(32)),
        clave_pvk=bytes(range(100, 116)),
        claves_pin_block={"TEST-KEY-01": bytes(range(32, 64))},
        referencia_pin_block="TEST-KEY-01",
    )
    e.factory.return_value = hsm
    inicial, referencia = hsm.construir_pin_block("7392", e.pan)
    offset, pvk = hsm.generar_offset(inicial, referencia, e.pan)
    e.estado.update(pin_offset=offset, referencia_clave_pvk=pvk)
    bloque, referencia = hsm.construir_pin_block(pin_ingresado, e.pan)
    if correcto:
        assert await service.autenticar_pin_ficticio_atm(e.conn, 1, bloque, referencia)
    else:
        e.resultado.return_value = {"intentos_fallidos": 1, "estado_pin": "Activo"}
        with pytest.raises(HTTPException) as error:
            await service.autenticar_pin_ficticio_atm(e.conn, 1, bloque, referencia)
        comprobar_error(error, 401, "PIN_INCORRECTO")
    e.resultado.assert_called_once_with(
        conn=e.conn_pin, id_tarjeta=1, pin_correcto=correcto
    )
    e.engine.begin.return_value.__exit__.assert_called_once_with(None, None, None)


# A-05: tarjeta de débito Generada con PIN temporal


@pytest.mark.anyio
async def test_pin_temporal_correcto_devuelve_requiere_cambio(entorno_atm):
    e = entorno_atm
    e.tarjeta.update(estado_tarjeta="Generada", tipo_tarjeta="Debito")
    e.estado.update(requiere_cambio=True)

    assert await autenticar(e) == service.PinVerificado(
        requiere_cambio=True, pin_version=VERSION_PIN
    )


@pytest.mark.anyio
async def test_debito_generada_sin_pin_temporal_409_sin_gastar_intentos(entorno_atm):
    e = entorno_atm
    e.tarjeta.update(estado_tarjeta="Generada", tipo_tarjeta="Debito")
    e.estado.update(requiere_cambio=False)

    with pytest.raises(HTTPException) as error:
        await autenticar(e)

    comprobar_error(error, 409, "TARJETA_NO_ACTIVA")
    e.hsm.verificar_pin.assert_not_called()
    e.resultado.assert_not_called()

"""Identificación y preparación de ATM-01; sin sesión ni terminal ficticios."""

import hashlib
import json
from datetime import date, timedelta
from typing import Annotated, Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import MultipleResultsFound

from app.core.api.errors import ProblemDetailsRoute, problema
from app.modules.atm import repository, router, service
from app.modules.atm.schemas import ATMAuthRequest
from app.modules.tarjetas import repository as tarjetas_repository
from app.modules.tarjetas.identificacion import hash_pan
from tests.pin_version import VERSION_PIN

PAN = "5000001234567896"
BLOQUE = "A" * 32
BODY = {
    "codigoATM": "ATM00001",
    "numeroTarjeta": PAN,
    "encryptedPinBlock": BLOQUE,
    "keyReference": "TEST-KEY-01",
}


@pytest.fixture(autouse=True)
def sin_base_real(monkeypatch):
    def prohibido(*args, **kwargs):
        raise AssertionError("Conexion real prohibida")

    monkeypatch.setattr("pyodbc.connect", prohibido)
    monkeypatch.setattr("sqlalchemy.create_engine", prohibido)
    monkeypatch.setattr("app.core.database.db.create_engine", prohibido)


def test_hash_compartido_es_el_binario_de_tar01():
    esperado = hashlib.sha256(PAN.encode()).digest()
    assert hash_pan(PAN) == esperado
    assert isinstance(hash_pan(PAN), bytes)
    assert len(hash_pan(PAN)) == 32


@pytest.mark.parametrize("id_tarjeta", [301, None])
def test_busqueda_parametrizada_no_envia_pan_a_sql(id_tarjeta):
    conn = MagicMock()
    conn.execute.return_value.scalar_one_or_none.return_value = id_tarjeta
    digest = hash_pan(PAN)
    assert tarjetas_repository.obtener_id_tarjeta_por_hash(conn, digest) == id_tarjeta
    sql, params = conn.execute.call_args.args
    assert "WHERE HashNumeroTarjeta = :hash_pan" in str(sql)
    assert params == {"hash_pan": digest}
    assert PAN not in str(sql)
    assert PAN not in str(params)


def test_busqueda_no_escoge_una_tarjeta_si_el_hash_esta_duplicado():
    conn = MagicMock()
    conn.execute.return_value.scalar_one_or_none.side_effect = MultipleResultsFound()
    with pytest.raises(MultipleResultsFound):
        tarjetas_repository.obtener_id_tarjeta_por_hash(conn, hash_pan(PAN))


def test_schema_contrato_aprobado_y_secretos_ocultos():
    entrada = ATMAuthRequest.model_validate(BODY)
    assert entrada.codigo_atm == "ATM00001"
    assert entrada.numero_tarjeta.get_secret_value() == PAN
    assert entrada.encrypted_pin_block.get_secret_value() == BLOQUE
    assert PAN not in repr(entrada)
    assert BLOQUE not in repr(entrada)
    assert PAN not in entrada.model_dump_json(by_alias=True)
    schema = ATMAuthRequest.model_json_schema()
    assert set(schema["properties"]) == set(BODY)
    assert set(schema["required"]) == set(BODY)
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("codigoATM", " ATM00001 "),
        ("codigoATM", "ATM0000"),
        ("codigoATM", 12345678),
        ("numeroTarjeta", "1" * 11),
        ("numeroTarjeta", "1" * 20),
        ("numeroTarjeta", "５０００００１２３４５６７８９６"),
        ("numeroTarjeta", "5000 0012 3456 7896"),
        ("numeroTarjeta", 5000001234567896),
        ("encryptedPinBlock", "A" * 31),
        ("encryptedPinBlock", "Z" * 32),
        ("keyReference", "TEST KEY"),
        ("keyReference", "K" * 33),
        ("idTarjeta", 301),
        ("pin", "7392"),
    ],
)
def test_schema_rechaza_entradas_fuera_de_contrato(campo, valor):
    with pytest.raises(ValidationError):
        ATMAuthRequest.model_validate({**BODY, campo: valor})


@pytest.mark.parametrize("pan", ["1" * 12, "1" * 19])
def test_schema_acepta_limites_de_longitud_pan(pan):
    assert ATMAuthRequest.model_validate({**BODY, "numeroTarjeta": pan})


def test_schema_no_acepta_alias_codigo_atm_anterior():
    datos = {k: v for k, v in BODY.items() if k != "codigoATM"}
    with pytest.raises(ValidationError):
        ATMAuthRequest.model_validate({**datos, "codigoAtm": "ATM00001"})


@pytest.fixture
def client():
    app = FastAPI()
    rutas = APIRouter(route_class=ProblemDetailsRoute)

    @rutas.post("/validar-entrada")
    async def validar(
        entrada: Annotated[ATMAuthRequest, Depends(router.leer_auth_atm)],
    ):
        return {"codigoATM": entrada.codigo_atm}

    app.include_router(rutas)
    return TestClient(app)


def test_lector_http_valida_sin_exponer_datos(client):
    response = client.post("/validar-entrada", json=BODY)
    assert response.status_code == 200
    assert response.json() == {"codigoATM": "ATM00001"}


@pytest.mark.parametrize(
    "contenido",
    [
        json.dumps({**BODY, "pin": "7392"}),
        json.dumps({**BODY, "numeroTarjeta": PAN + "X"}),
        json.dumps({**BODY, "encryptedPinBlock": BLOQUE + "X"}),
        '{"numeroTarjeta":"' + PAN + '",',
        json.dumps(BODY)[:-1] + ',"numeroTarjeta":"' + PAN + '"}',
        "[]",
        "null",
    ],
)
def test_lector_http_errores_no_filtran_body(client, caplog, contenido):
    response = client.post(
        "/validar-entrada",
        content=contenido,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "DATOS_INVALIDOS"
    assert PAN not in response.text + caplog.text
    assert BLOQUE not in response.text + caplog.text
    assert "7392" not in response.text + caplog.text


def test_lector_http_limita_cuerpo(client):
    response = client.post(
        "/validar-entrada",
        content=" " * 2049,
        headers={"Content-Type": "application/json", "Content-Length": "1"},
    )
    assert response.status_code == 413


def test_lector_http_rechaza_content_type_y_query(client):
    assert client.post("/validar-entrada", content=json.dumps(BODY)).status_code == 415
    assert (
        client.post("/validar-entrada?numeroTarjeta=prohibido", json=BODY).status_code
        == 400
    )


def test_router_publica_auth_logout_consulta_saldo_y_cambio_pin():
    assert [cast(APIRoute, ruta).path for ruta in router.router.routes] == [
        "/atm/auth",
        "/atm/logout",
        "/atm/consulta-saldo",
        "/atm/cambio-pin",
        "/atm/transferencias",
    ]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def entorno(monkeypatch):
    e = MagicMock()
    e.leer_atm.return_value = {
        "id_atm": 1,
        "tipo_terminal": "ATM",
        "estado_atm": "A",
        "estado_canal": "A",
        "requiere_tarjeta": True,
        "requiere_pin": True,
        "requiere_terminal": True,
    }
    e.resolver.return_value = 301
    e.leer_tarjeta.return_value = {
        "estado_tarjeta": "Activa",
        "pin_asignado": True,
        "fecha_expiracion": date.today() + timedelta(days=30),
        "nombres_titular": "Maria",
        "apellidos_titular": "Mendoza",
    }
    e.cuentas.return_value = [
        {"id_cuenta": 501, "numero_cuenta": "1234567890501", "tipo_cuenta": "Ahorro"}
    ]
    e.pin = AsyncMock(
        return_value=service.PinVerificado(
            requiere_cambio=False, pin_version=VERSION_PIN
        )
    )
    monkeypatch.setattr(repository, "obtener_atm", e.leer_atm)
    monkeypatch.setattr(repository, "obtener_tarjeta", e.leer_tarjeta)
    monkeypatch.setattr(repository, "obtener_cuentas_autorizadas", e.cuentas)
    monkeypatch.setattr(tarjetas_repository, "obtener_id_tarjeta_por_hash", e.resolver)
    monkeypatch.setattr(service, "autenticar_pin_ficticio_atm", e.pin)
    return e


@pytest.mark.anyio
async def test_flujo_interno_resuelve_id_y_reutiliza_autenticacion(entorno):
    e = entorno
    resultado = await service.validar_acceso_atm(
        e.conn, ATMAuthRequest.model_validate(BODY)
    )
    e.resolver.assert_called_once_with(e.conn, hash_pan(PAN))
    e.pin.assert_awaited_once_with(e.conn, 301, BLOQUE, "TEST-KEY-01")
    e.cuentas.assert_called_once_with(e.conn, 301)
    assert resultado.id_atm == 1
    assert resultado.id_tarjeta == 301
    assert resultado.titular == "Maria Mendoza"
    assert resultado.cuentas[0].numero_cuenta_enmascarado == "*********0501"
    assert PAN not in repr(resultado)
    assert BLOQUE not in repr(resultado)
    assert "1234567890501" not in repr(resultado)
    assert not hasattr(resultado, "session_token")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fallo,code",
    [
        ("terminal", "ATM_FUERA_DE_SERVICIO"),
        ("inexistente", "TARJETA_NO_ACTIVA"),
        ("inactiva", "TARJETA_NO_ACTIVA"),
        ("bloqueada", "TARJETA_BLOQUEADA"),
    ],
)
async def test_precondiciones_impiden_verificar_pin(entorno, fallo, code):
    e = entorno
    if fallo == "terminal":
        e.leer_atm.return_value["estado_atm"] = "I"
    elif fallo == "inexistente":
        e.resolver.return_value = None
    else:
        e.leer_tarjeta.return_value["estado_tarjeta"] = (
            "Bloqueada" if fallo == "bloqueada" else "Generada"
        )
    with pytest.raises(HTTPException) as error:
        await service.validar_acceso_atm(e.conn, ATMAuthRequest.model_validate(BODY))
    assert cast(dict[str, Any], error.value.detail)["code"] == code
    e.pin.assert_not_awaited()
    e.cuentas.assert_not_called()


@pytest.mark.anyio
async def test_pin_incorrecto_no_consulta_cuentas(entorno):
    e = entorno
    e.pin.side_effect = problema(
        401, "PIN_INCORRECTO", "El PIN ingresado es incorrecto."
    )
    with pytest.raises(HTTPException):
        await service.validar_acceso_atm(e.conn, ATMAuthRequest.model_validate(BODY))
    e.cuentas.assert_not_called()


@pytest.mark.anyio
async def test_sin_cuentas_operables_no_prepara_sesion(entorno):
    e = entorno
    e.cuentas.return_value = []
    with pytest.raises(HTTPException) as error:
        await service.validar_acceso_atm(e.conn, ATMAuthRequest.model_validate(BODY))
    assert cast(dict[str, Any], error.value.detail)["code"] == "CUENTA_NO_ACTIVA"


def test_cuentas_sql_solo_cuenta_vinculada_activa():
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value = []
    assert repository.obtener_cuentas_autorizadas(conn, 301) == []
    sql, params = conn.execute.call_args.args
    assert "c.IdCuenta = t.IdCuenta" in str(sql)
    assert "t.IdTarjeta = :id_tarjeta" in str(sql)
    assert "c.Estado = 'Activa'" in str(sql)
    assert "t.Estado = 'Activa'" in str(sql)
    assert params == {"id_tarjeta": 301}


# A-05: sesión restringida y activación de crédito


@pytest.mark.anyio
async def test_pin_temporal_prepara_sesion_restringida_sin_cuentas(entorno):
    e = entorno
    e.pin.return_value = service.PinVerificado(
        requiere_cambio=True, pin_version=VERSION_PIN
    )

    resultado = await service.validar_acceso_atm(
        e.conn, ATMAuthRequest.model_validate(BODY)
    )

    assert resultado.pin_version == VERSION_PIN
    assert resultado.cambio_pin_requerido is True and resultado.cuentas == []
    assert resultado.titular == "Maria Mendoza"
    e.cuentas.assert_not_called()


@pytest.mark.anyio
async def test_credito_generada_se_activa_tras_pin_correcto(entorno, monkeypatch):
    e = entorno
    e.leer_atm.return_value["id_canal"] = 4
    e.leer_tarjeta.return_value.update(
        estado_tarjeta="Generada",
        tipo_tarjeta="Credito",
        fecha_emision=date.today() - timedelta(days=7),
    )
    monkeypatch.setattr(tarjetas_repository, "dias_laborables_desde", lambda *_: 3)
    activar = MagicMock()
    monkeypatch.setattr(repository, "activar_tarjeta_credito", activar)
    conn_activacion = MagicMock()
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn_activacion
    monkeypatch.setattr(service, "get_engine", lambda _db: engine)

    resultado = await service.validar_acceso_atm(
        e.conn, ATMAuthRequest.model_validate(BODY), usuario_bloqueo=900, ip="1.2.3.4"
    )

    activar.assert_called_once_with(conn_activacion, 301, 4, 900, "1.2.3.4")
    assert resultado.cambio_pin_requerido is False and resultado.cuentas

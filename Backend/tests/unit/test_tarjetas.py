"""TAR-01..06 sin BD, con el repositorio simulado.

401 y 403 quedan para cuando exista F-03. Mientras tanto se prueba que las rutas se
cierran fuera de development.
"""

import hashlib
import logging
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.core.database.db import cooperativa
from app.main import app
from app.modules.tarjetas import repository, router, service

BASE = "/api/v1/tarjetas"
PAYLOAD = {
    "idCuenta": 4,
    "idProducto": 4,
    "tipoTarjeta": "Debito",
    "nombreTarjeta": "MARIA MENDOZA",
}
CUENTA = {
    "id_cuenta": 4,
    "id_cliente": 4,
    "id_agencia": "002",
    "estado": "Activa",
    "nombres": "Maria",
    "apellidos": None,
}
FILA = {
    "id_tarjeta": 301,
    "token_tarjeta": "tok_x",
    "numero_enmascarado": "5000 00** **** 1234",
    "tipo_tarjeta": "Debito",
    "nombre_tarjeta": "MARIA MENDOZA",
    "id_cliente": 4,
    "id_cuenta": 4,
    "id_producto": 4,
    "estado_actual": "Generada",
    "pin_asignado": False,
    "fecha_emision": date(2026, 11, 1),
    "fecha_expiracion": date(2031, 11, 1),
}
SUBPRODUCTO = {"id_sub_producto": 3, "id_bin": 1, "codigo_bin": "500000"}


class _Conn:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture()
def conns():
    return SimpleNamespace(coop=_Conn(), seg=_Conn())


@pytest.fixture()
def client(conns):
    app.dependency_overrides[cooperativa] = lambda: conns.coop
    app.dependency_overrides[router.seguridad] = lambda: conns.seg
    app.dependency_overrides[router.autorizacion_disponible] = lambda: None
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture()
def emision(monkeypatch):
    """Repositorio listo para emitir; guarda lo que se inserta."""
    capturado: dict[str, Any] = {}
    monkeypatch.setattr(repository, "obtener_cuenta", lambda c, i: CUENTA)
    monkeypatch.setattr(
        repository,
        "obtener_producto",
        lambda c, i: {"tipo_producto": "Tarjeta", "estado": "A"},
    )
    monkeypatch.setattr(
        repository, "obtener_subproducto_con_bin", lambda c, i: SUBPRODUCTO
    )
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda c, i, **k: FILA)
    monkeypatch.setattr(repository, "existe_ciudad", lambda c, i: True)

    def insertar(_conn, datos):
        capturado["tarjeta"] = datos
        return 301

    monkeypatch.setattr(repository, "insertar_tarjeta", insertar)
    monkeypatch.setattr(
        repository,
        "insertar_envio",
        lambda *a: capturado.__setitem__("envio", a),
    )
    monkeypatch.setattr(
        repository,
        "insertar_historial",
        lambda *a: capturado.__setitem__("historial", a),
    )
    return capturado


def _code(respuesta) -> str:
    return respuesta.json()["code"]


# TAR-01


def test_emitir_201_nace_generada_sin_pan_ni_hash(client, conns, emision):
    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["estadoActual"] == "Generada"
    assert cuerpo["pinAsignado"] is False
    assert "hashNumeroTarjeta" not in cuerpo
    assert conns.coop.commits == 1
    assert "envio" not in emision
    assert emision["historial"][2:5] == ("CambioEstado", None, "Generada")
    assert r.headers["cache-control"] == "no-store"


def test_emitir_guarda_mascara_y_hash_que_corresponden_a_un_pan_luhn(client, emision):
    client.post(BASE, json=PAYLOAD)

    datos = emision["tarjeta"]
    assert len(datos["mascara"]) == 19
    assert datos["mascara"].startswith("5000 00** **** ")
    assert len(datos["hash_pan"]) == hashlib.sha256().digest_size
    assert datos["token"].startswith("tok_")
    assert not any(
        isinstance(v, str) and v.isdigit() and len(v) >= 13 for v in datos.values()
    )


def test_pan_generado_cumple_luhn_y_longitud():
    pan = service._generar_pan("500000")
    total = 0
    for i, c in enumerate(reversed(pan)):
        d = int(c) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    assert len(pan) == 16 and pan.startswith("500000") and total % 10 == 0


@pytest.mark.parametrize(
    "cuenta", [None, {**CUENTA, "estado": "Bloqueada"}, {**CUENTA, "estado": "Cerrada"}]
)
def test_emitir_cuenta_no_activa_409(client, conns, emision, monkeypatch, cuenta):
    monkeypatch.setattr(repository, "obtener_cuenta", lambda c, i: cuenta)

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 409 and _code(r) == "CUENTA_NO_ACTIVA"
    assert conns.coop.rollbacks == 1 and conns.coop.commits == 0


@pytest.mark.parametrize(
    "producto",
    [
        None,
        {"tipo_producto": "Cuenta", "estado": "A"},
        {"tipo_producto": "Tarjeta", "estado": "I"},
    ],
)
def test_emitir_producto_incorrecto_422(client, emision, monkeypatch, producto):
    monkeypatch.setattr(repository, "obtener_producto", lambda c, i: producto)

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 422 and _code(r) == "PRODUCTO_NO_ES_TARJETA"


def test_emitir_sin_bin_activo_422(client, emision, monkeypatch):
    monkeypatch.setattr(repository, "obtener_subproducto_con_bin", lambda c, i: None)

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 422 and _code(r) == "BIN_INVALIDO"


def _error_db(mensaje: str) -> DBAPIError:
    return DBAPIError("SELECT 1", {"p": "SECRETO"}, Exception(mensaje))


def test_emitir_bin_distinto_en_trigger_422(client, conns, emision, monkeypatch):
    def falla(*_a):
        raise _error_db("[SQL Server]El BIN debe coincidir (52004) (SQLExecDirectW)")

    monkeypatch.setattr(repository, "insertar_tarjeta", falla)

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 422 and _code(r) == "BIN_INVALIDO"
    assert conns.coop.rollbacks == 1


@pytest.mark.parametrize(
    ("extra", "titular"),
    [
        ({"esExtension": True}, None),
        ({"esExtension": True, "idTarjetaTitular": 9}, None),
        (
            {"esExtension": True, "idTarjetaTitular": 9},
            {"id_cuenta": 99, "es_extension": False, "estado": "Activa"},
        ),
        (
            {"esExtension": True, "idTarjetaTitular": 9},
            {"id_cuenta": 4, "es_extension": True, "estado": "Activa"},
        ),
        (
            {"esExtension": True, "idTarjetaTitular": 9},
            {"id_cuenta": 4, "es_extension": False, "estado": "Cancelada"},
        ),
        ({"esExtension": False, "idTarjetaTitular": 9}, None),
    ],
)
def test_emitir_extension_sin_titular_valido_422(
    client, emision, monkeypatch, extra, titular
):
    monkeypatch.setattr(repository, "obtener_titular", lambda c, i: titular)

    r = client.post(BASE, json={**PAYLOAD, **extra})

    assert r.status_code == 422 and _code(r) == "EXTENSION_REQUIERE_TITULAR"


def test_emitir_extension_valida_201(client, emision, monkeypatch):
    monkeypatch.setattr(
        repository,
        "obtener_titular",
        lambda c, i: {"id_cuenta": 4, "es_extension": False, "estado": "Activa"},
    )

    r = client.post(BASE, json={**PAYLOAD, "esExtension": True, "idTarjetaTitular": 9})

    assert r.status_code == 201
    assert emision["tarjeta"]["id_titular"] == 9


def test_emitir_con_envio_crea_envio(client, emision):
    r = client.post(
        BASE,
        json={
            **PAYLOAD,
            "requiereEnvio": True,
            "direccionEnvio": "Av. Amazonas 123",
            "idCiudadEnvio": 1,
        },
    )

    assert r.status_code == 201
    assert emision["envio"][2:] == (4, "Av. Amazonas 123", 1)


def test_emitir_envio_sin_direccion_422(client, emision):
    r = client.post(BASE, json={**PAYLOAD, "requiereEnvio": True})

    assert r.status_code == 422 and _code(r) == "DIRECCION_ENVIO_REQUERIDA"


def test_emitir_envio_ciudad_inexistente_422(client, emision, monkeypatch):
    monkeypatch.setattr(repository, "existe_ciudad", lambda c, i: False)

    r = client.post(
        BASE,
        json={
            **PAYLOAD,
            "requiereEnvio": True,
            "direccionEnvio": "Av. 1",
            "idCiudadEnvio": 99,
        },
    )

    assert r.status_code == 422 and _code(r) == "CIUDAD_NO_ENCONTRADA"


@pytest.mark.parametrize(
    "cambio",
    [
        {"estado": "Activa"},  # no está en el contrato
        {"tipoTarjeta": "Prepago"},
        {"nombreTarjeta": ""},
        {"nombreTarjeta": "<script>alert(1)</script>"},
        {"nombreTarjeta": "A" * 51},
        {"idCuenta": "4"},
        {"idCuenta": 2_147_483_648},
        {"idCuenta": -1},
        {"direccionEnvio": "linea\r\ninyectada"},
    ],
)
def test_emitir_body_invalido_400(client, cambio):
    assert client.post(BASE, json={**PAYLOAD, **cambio}).status_code == 400


# TAR-02


def _lista(monkeypatch):
    llamada: dict[str, Any] = {}

    def listar(_c, *args):
        llamada["args"] = args
        return [FILA], 1

    monkeypatch.setattr(repository, "listar_tarjetas", listar)
    return llamada


def test_buscar_200_sin_token_ni_pin(client, monkeypatch):
    llamada = _lista(monkeypatch)

    r = client.get(
        BASE, params={"idCliente": 4, "estado": "Generada", "sort": "fechaEmision,asc"}
    )

    assert r.status_code == 200
    cuerpo = r.json()
    assert (cuerpo["page"], cuerpo["pageSize"], cuerpo["total"]) == (1, 20, 1)
    item = cuerpo["items"][0]
    assert item["numeroEnmascarado"] == FILA["numero_enmascarado"]
    assert "tokenTarjeta" not in item
    assert "pinAsignado" not in item
    assert llamada["args"] == (4, None, "Generada", "fechaEmision", "asc", 1, 20)


@pytest.mark.parametrize(
    "params",
    [
        {"pageSize": 101},
        {"pageSize": 0},
        {"page": 0},
        {"estado": "NoExiste"},
        {"idCliente": "abc"},
    ],
)
def test_buscar_filtros_invalidos_400(client, params):
    assert client.get(BASE, params=params).status_code == 400


@pytest.mark.parametrize(
    "sort",
    ["IdTarjeta;DROP TABLE x", "hashNumeroTarjeta,asc", "idTarjeta,sideways"],
)
def test_buscar_sort_fuera_de_lista_400(client, sort):
    r = client.get(BASE, params={"sort": sort})

    assert r.status_code == 400 and _code(r) == "SORT_INVALIDO"


@pytest.mark.parametrize("query", ["page=1&page=2", "otro=1"])
def test_buscar_parametros_ambiguos_400(client, query):
    r = client.get(f"{BASE}?{query}")

    assert r.status_code == 400 and _code(r) == "PARAMETRO_INVALIDO"


# TAR-03


def test_detalle_200_enmascarado(client, monkeypatch):
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda c, i, **k: FILA)

    r = client.get(f"{BASE}/301")

    assert r.status_code == 200
    assert r.json()["numeroEnmascarado"] == FILA["numero_enmascarado"]
    assert r.json()["fechaExpiracion"] == "2031-11-01"


def test_detalle_inexistente_404(client, monkeypatch):
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda c, i, **k: None)

    r = client.get(f"{BASE}/999")

    assert r.status_code == 404 and _code(r) == "TARJETA_NO_ENCONTRADA"


@pytest.mark.parametrize("valor", ["abc", "0", "2147483648"])
def test_detalle_id_invalido_400(client, valor):
    assert client.get(f"{BASE}/{valor}").status_code == 400


# TAR-04


def _estado(monkeypatch, fila, transicion=True):
    capturado: dict[str, Any] = {}
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda c, i, **k: fila)
    monkeypatch.setattr(repository, "existe_transicion", lambda c, o, d: transicion)
    monkeypatch.setattr(
        repository,
        "actualizar_estado",
        lambda c, i, e: capturado.__setitem__("estado", e),
    )
    monkeypatch.setattr(
        repository,
        "insertar_historial",
        lambda *a: capturado.__setitem__("historial", a),
    )
    return capturado


@pytest.mark.parametrize(
    ("anterior", "destino", "evento"),
    [
        ("Generada", "Activa", "Activacion"),
        ("Activa", "Bloqueada", "Bloqueo"),
        ("Bloqueada", "Activa", "Desbloqueo"),
        ("Generada", "Anulada", "Anulacion"),
        ("Activa", "Cancelada", "CambioEstado"),
    ],
)
def test_estado_valido_200_registra_historial(
    client, conns, monkeypatch, anterior, destino, evento
):
    capturado = _estado(
        monkeypatch, {**FILA, "estado_actual": anterior, "pin_asignado": True}
    )

    r = client.post(
        f"{BASE}/301/estado", json={"estado": destino, "motivo": " Motivo "}
    )

    assert r.status_code == 200
    assert capturado["estado"] == destino
    assert capturado["historial"][2:6] == (evento, anterior, destino, "Motivo")
    assert capturado["historial"][7] == "testclient"
    assert conns.coop.commits == 1


def test_estado_transicion_invalida_409(client, conns, monkeypatch):
    capturado = _estado(monkeypatch, FILA, transicion=False)

    r = client.post(f"{BASE}/301/estado", json={"estado": "Bloqueada", "motivo": "x"})

    assert r.status_code == 409 and _code(r) == "TRANSICION_TARJETA_INVALIDA"
    assert "estado" not in capturado and conns.coop.commits == 0


def test_activar_sin_pin_409(client, monkeypatch):
    capturado = _estado(monkeypatch, FILA)

    r = client.post(f"{BASE}/301/estado", json={"estado": "Activa", "motivo": "x"})

    assert r.status_code == 409 and _code(r) == "TRANSICION_TARJETA_INVALIDA"
    assert "estado" not in capturado


def test_estado_inexistente_404(client, monkeypatch):
    _estado(monkeypatch, None)

    r = client.post(f"{BASE}/9/estado", json={"estado": "Activa", "motivo": "x"})

    assert r.status_code == 404


def test_estado_trigger_52005_409_sin_filtrar_sql(client, conns, monkeypatch):
    _estado(monkeypatch, {**FILA, "pin_asignado": True})

    def falla(*_a):
        raise _error_db("[SQL Server]Cambio no permitido (52005) (SQLExecDirectW)")

    monkeypatch.setattr(repository, "actualizar_estado", falla)

    r = client.post(f"{BASE}/301/estado", json={"estado": "Activa", "motivo": "x"})

    assert r.status_code == 409 and _code(r) == "TRANSICION_TARJETA_INVALIDA"
    assert "SQL" not in r.text and "SECRETO" not in r.text
    assert conns.coop.rollbacks == 1


@pytest.mark.parametrize(
    "body",
    [
        {"estado": "Activa"},
        {"estado": "Activa", "motivo": "   "},
        {"estado": "Cerrada", "motivo": "x"},
        {"estado": "Activa", "motivo": "x" * 501},
        {"estado": "Activa", "motivo": "x", "pinAsignado": True},
    ],
)
def test_estado_body_invalido_400(client, body):
    assert client.post(f"{BASE}/301/estado", json=body).status_code == 400


# TAR-05


def _pin(monkeypatch, fila=FILA, marcado=True):
    capturado: dict[str, Any] = {}
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda c, i, **k: fila)
    monkeypatch.setattr(repository, "marcar_pin_asignado", lambda c, i: marcado)
    monkeypatch.setattr(
        repository,
        "insertar_historial",
        lambda *a: capturado.__setitem__("historial", a),
    )
    monkeypatch.setattr(
        repository,
        "guardar_hash_pin",
        lambda c, i, h: capturado.__setitem__("hash", h),
    )
    return capturado


def test_pin_204_guarda_argon2id_y_confirma_en_ambas_bd(client, conns, monkeypatch):
    capturado = _pin(monkeypatch)

    r = client.post(f"{BASE}/301/pin", json={"pin": "7392"})

    assert r.status_code == 204 and r.content == b""
    assert capturado["hash"].startswith("$argon2id$")
    assert "7392" not in capturado["hash"]
    assert PasswordHasher().verify(capturado["hash"], "7392")
    assert capturado["historial"][2] == "CambioPin"
    assert "7392" not in str(capturado["historial"])
    assert conns.coop.commits == 1 and conns.seg.commits == 1


def test_pin_ya_asignado_409(client, monkeypatch):
    capturado = _pin(monkeypatch, {**FILA, "pin_asignado": True})

    r = client.post(f"{BASE}/301/pin", json={"pin": "7392"})

    assert r.status_code == 409 and _code(r) == "PIN_YA_ASIGNADO"
    assert "hash" not in capturado


def test_pin_carrera_concurrente_409(client, conns, monkeypatch):
    capturado = _pin(monkeypatch, marcado=False)

    r = client.post(f"{BASE}/301/pin", json={"pin": "7392"})

    assert r.status_code == 409 and _code(r) == "PIN_YA_ASIGNADO"
    assert "hash" not in capturado and conns.seg.commits == 0


def test_pin_tarjeta_inexistente_404(client, monkeypatch):
    _pin(monkeypatch, None)

    assert client.post(f"{BASE}/9/pin", json={"pin": "7392"}).status_code == 404


@pytest.mark.parametrize("pin", ["0000", "1111", "1234", "4321", "6789", "9876"])
def test_pin_debil_422_sin_guardar(client, monkeypatch, pin):
    capturado = _pin(monkeypatch)

    r = client.post(f"{BASE}/301/pin", json={"pin": pin})

    assert r.status_code == 422 and _code(r) == "PIN_DEBIL"
    assert "hash" not in capturado
    assert pin not in r.text


@pytest.mark.parametrize("pin", ["1235", "2580", "1212", "7392", "0001"])
def test_pin_no_trivial_es_aceptado(pin):
    assert service.es_pin_debil(pin) is False


@pytest.mark.parametrize(
    "contenido",
    [
        b'{"pin": "73"}',
        b'{"pin": "739256"}',
        b'{"pin": "abcd"}',
        b'{"pin": 7392}',
        b'{"pin": null}',
        b'{"pin": "\xd9\xa1\xd9\xa2\xd9\xa3\xd9\xa4"}',  # dígitos arábigos
        b'{"pinn": "7392"}',
        b'{"pin": "7392", "x": "7392"}',
        b'"7392"',
        b"7392",
        b"{no json 7392",
        b"",
        b'{"pin": "7392", "relleno": "' + b"x" * 2000 + b'"}',
    ],
)
def test_pin_invalido_400_nunca_repite_el_valor(client, monkeypatch, contenido):
    capturado = _pin(monkeypatch)

    r = client.post(
        f"{BASE}/301/pin",
        content=contenido,
        headers={"content-type": "application/json"},
    )

    assert r.status_code == 400 and _code(r) == "PIN_INVALIDO"
    assert "7392" not in r.text
    assert "hash" not in capturado


def test_pin_no_aparece_en_logs(client, monkeypatch, caplog):
    _pin(monkeypatch)
    caplog.set_level(logging.DEBUG)

    client.post(f"{BASE}/301/pin", json={"pin": "7392"})
    client.post(f"{BASE}/301/pin", json={"pin": "1234"})

    assert "7392" not in caplog.text
    assert "1234" not in caplog.text


def test_pin_fallo_de_bd_revierte_ambas_y_no_filtra_nada(
    client, conns, monkeypatch, caplog
):
    _pin(monkeypatch)
    caplog.set_level(logging.DEBUG)

    def falla(*_a):
        raise DBAPIError("UPDATE x", {"hash_pin": "SECRETO"}, Exception("caida"))

    monkeypatch.setattr(repository, "guardar_hash_pin", falla)

    r = client.post(f"{BASE}/301/pin", json={"pin": "7392"})

    assert r.status_code == 500 and _code(r) == "ERROR_INTERNO"
    assert conns.coop.rollbacks == 1 and conns.seg.rollbacks == 1
    assert conns.coop.commits == 0 and conns.seg.commits == 0
    for texto in (r.text, caplog.text):
        assert "SECRETO" not in texto and "UPDATE" not in texto


# TAR-06

EVENTOS = [
    {
        "id_historial": 2,
        "id_tarjeta": 301,
        "tipo_evento": "Bloqueo",
        "estado_anterior": "Activa",
        "estado_nuevo": "Bloqueada",
        "descripcion": "Extravío",
        "fecha_evento": datetime(2026, 10, 26, 15, 30),
        "realizado_por": 12,
    },
    {
        "id_historial": 1,
        "id_tarjeta": 301,
        "tipo_evento": "CambioPin",
        "estado_anterior": None,
        "estado_nuevo": None,
        "descripcion": "Asignación de PIN inicial",
        "fecha_evento": datetime(2026, 10, 24, 9, 0),
        "realizado_por": 15,
    },
]


def test_historial_200_desc_con_zona_y_sin_datos_internos(client, monkeypatch):
    llamada: dict[str, Any] = {}
    monkeypatch.setattr(repository, "existe_tarjeta", lambda c, i: True)

    def listar(_c, *args):
        llamada["args"] = args
        return EVENTOS, 2

    monkeypatch.setattr(repository, "listar_historial", listar)

    r = client.get(f"{BASE}/301/historial")

    assert r.status_code == 200
    assert llamada["args"] == (301, None, None, "fechaCambio", "desc", 1, 20)
    bloqueo, pin = r.json()["items"]
    assert bloqueo["estadoNuevo"] == "Bloqueada"
    assert bloqueo["motivo"] == "Extravío"
    assert bloqueo["fechaCambio"] == "2026-10-26T15:30:00-05:00"
    assert pin["resultado"] == "COMPLETADO"
    assert "motivo" not in pin and "estadoNuevo" not in pin
    assert "direccionIP" not in r.text and "idCanal" not in r.text


def test_historial_pasa_el_filtro_de_fechas(client, monkeypatch):
    llamada: dict[str, Any] = {}
    monkeypatch.setattr(repository, "existe_tarjeta", lambda c, i: True)

    def listar(_c, *args):
        llamada["args"] = args
        return [], 0

    monkeypatch.setattr(repository, "listar_historial", listar)

    r = client.get(
        f"{BASE}/301/historial",
        params={"fechaDesde": "2026-10-01", "fechaHasta": "2026-10-31"},
    )

    assert r.status_code == 200
    assert llamada["args"][1:3] == (date(2026, 10, 1), date(2026, 10, 31))


def test_historial_rango_de_fechas_invertido_400(client):
    r = client.get(
        f"{BASE}/301/historial",
        params={"fechaDesde": "2026-10-31", "fechaHasta": "2026-10-01"},
    )

    assert r.status_code == 400 and _code(r) == "RANGO_FECHAS_INVALIDO"


def test_historial_fecha_mal_formada_400(client):
    r = client.get(f"{BASE}/301/historial", params={"fechaDesde": "ayer"})

    assert r.status_code == 400


def test_historial_tarjeta_inexistente_404(client, monkeypatch):
    monkeypatch.setattr(repository, "existe_tarjeta", lambda c, i: False)

    assert client.get(f"{BASE}/9/historial").status_code == 404


@pytest.mark.parametrize(
    "params", [{"pageSize": 101}, {"page": 0}, {"sort": "DireccionIP,asc"}]
)
def test_historial_parametros_invalidos_400(client, params):
    assert client.get(f"{BASE}/301/historial", params=params).status_code == 400


# Transversales


@pytest.mark.parametrize(
    ("metodo", "ruta", "body"),
    [
        ("post", BASE, PAYLOAD),
        ("get", BASE, None),
        ("get", f"{BASE}/1", None),
        ("post", f"{BASE}/1/estado", {"estado": "Activa", "motivo": "x"}),
        ("post", f"{BASE}/1/pin", {"pin": "7392"}),
        ("get", f"{BASE}/1/historial", None),
    ],
)
@pytest.mark.parametrize("entorno", ["staging", "production"])
def test_rutas_cerradas_fuera_de_desarrollo_sin_f03(
    conns, monkeypatch, metodo, ruta, body, entorno
):
    app.dependency_overrides[cooperativa] = lambda: conns.coop
    app.dependency_overrides[router.seguridad] = lambda: conns.seg
    monkeypatch.setattr(
        router, "get_settings", lambda: SimpleNamespace(app_env=entorno)
    )
    try:
        r = getattr(TestClient(app), metodo)(
            ruta, **({"json": body} if body is not None else {})
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 503 and _code(r) == "AUTORIZACION_NO_DISPONIBLE"


def test_openapi_documenta_las_seis_rutas_y_el_body_del_pin():
    rutas = app.openapi()["paths"]

    assert set(rutas[BASE]) == {"post", "get"}
    assert "get" in rutas[f"{BASE}/{{idTarjeta}}"]
    assert "post" in rutas[f"{BASE}/{{idTarjeta}}/estado"]
    assert "get" in rutas[f"{BASE}/{{idTarjeta}}/historial"]
    esquema = rutas[f"{BASE}/{{idTarjeta}}/pin"]["post"]["requestBody"]["content"]
    assert esquema["application/json"]["schema"]["required"] == ["pin"]

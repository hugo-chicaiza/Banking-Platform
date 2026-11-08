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
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.core.database.db import cooperativa
from app.core.security.auth import ROLES
from app.core.security.hsm import HsmNoDisponible, es_pin_debil
from app.main import app
from app.modules.tarjetas import repository, router, service
from tests.sesion import simular_sesion, usuario_con_roles
from tests.tarjetas_hsm import HSM, PAN, instalar, pin_generado, pin_valido

BASE = "/api/v1/tarjetas"
PAYLOAD = {
    "idCuenta": 4,
    "idProducto": 4,
    "idSubProducto": 3,
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
    "estado_actual": "Solicitada",
    "es_extension": False,
    "id_tarjeta_titular": None,
    "pin_asignado": False,
    "fecha_solicitud": date(2026, 11, 1),
    "fecha_resolucion": None,
    "fecha_emision": date(2026, 11, 1),
    "fecha_expiracion": date(2031, 11, 1),
}
SUBPRODUCTO = {
    "id_sub_producto": 3,
    "estado": "A",
    "codigo_sub_producto": "TDB001-MC",
    "id_bin": 1,
    "codigo_bin": "500000",
    "estado_bin": "A",
}


class _Conn:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.falla_commit: Exception | None = None

    def commit(self) -> None:
        if self.falla_commit is not None:
            raise self.falla_commit
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture()
def conns():
    return SimpleNamespace(coop=_Conn(), seg=_Conn())


@pytest.fixture(autouse=True)
def fuera_de_produccion(monkeypatch):
    """El CI corre sin .env (APP_ENV=production por defecto): el PIN pad simulado se
    prueba como en development.
    """
    monkeypatch.setattr(
        router, "get_settings", lambda: SimpleNamespace(app_env="development")
    )


@pytest.fixture(autouse=True)
def seg(monkeypatch):
    """HSM simulado con claves fijas y SeguridadDB (PAN ficticio, TarjetaPIN) en memoria."""
    return instalar(monkeypatch)


@pytest.fixture()
def client(conns):
    app.dependency_overrides[cooperativa] = lambda: conns.coop
    app.dependency_overrides[router.seguridad] = lambda: conns.seg
    simular_sesion(app)
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
        repository, "obtener_subproducto_con_bin", lambda c, i, s: SUBPRODUCTO
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


def test_emitir_201_nace_solicitada_sin_pin_pan_ni_hash(client, conns, emision):
    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["estadoActual"] == "Solicitada"
    assert cuerpo["pinAsignado"] is False
    assert cuerpo["fechaSolicitud"] == "2026-11-01"
    assert cuerpo["fechaResolucion"] is None
    assert "hashNumeroTarjeta" not in cuerpo
    assert conns.coop.commits == 1
    assert "envio" not in emision
    assert emision["historial"][2:5] == ("CambioEstado", None, "Solicitada")
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


def test_emitir_custodia_el_pan_cifrado_y_coincide_con_hash_y_mascara(
    client, conns, emision, seg
):
    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 201
    cifrado, referencia = seg.pans[301]
    pan = HSM.descifrar_pan(cifrado, referencia, 301)
    datos = emision["tarjeta"]
    assert hashlib.sha256(pan.encode()).digest() == datos["hash_pan"]
    assert service._enmascarar(pan) == datos["mascara"]
    assert pan.encode() not in cifrado
    # SeguridadDB (PAN) se confirma antes que CooperativaDB (tarjeta)
    assert conns.seg.commits == 1 and conns.coop.commits == 1


def test_emitir_no_expone_el_pan_en_respuesta_ni_logs(client, emision, seg, caplog):
    caplog.set_level(logging.DEBUG)

    r = client.post(BASE, json=PAYLOAD)

    cifrado, referencia = seg.pans[301]
    pan = HSM.descifrar_pan(cifrado, referencia, 301)
    assert pan not in r.text and pan not in caplog.text


def test_emitir_sin_hsm_503_sin_crear_nada(client, conns, emision, seg, monkeypatch):
    def sin_hsm():
        raise HsmNoDisponible("x")

    monkeypatch.setattr(service, "obtener_hsm", sin_hsm)

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 503 and _code(r) == "PAN_NO_DISPONIBLE"
    assert "tarjeta" not in emision and seg.pans == {}
    assert conns.coop.commits == 0


def test_emitir_fallo_al_custodiar_revierte_la_tarjeta(
    client, conns, emision, seg, monkeypatch
):
    def falla(*_a):
        raise DBAPIError("INSERT x", {}, Exception("caida"))

    monkeypatch.setattr(repository, "guardar_pan_ficticio", falla)

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 500
    assert conns.coop.commits == 0 and conns.coop.rollbacks >= 1


def test_emitir_si_falla_cooperativa_se_borra_el_pan_custodiado(
    client, conns, emision, seg
):
    conns.coop.falla_commit = DBAPIError("COMMIT", {}, Exception("caida"))

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 500
    # Sin tarjeta confirmada no queda PAN huérfano
    assert seg.pans == {}


def test_pan_generado_cumple_luhn_y_longitud():
    pan = service._generar_pan("500000")
    total = 0
    for i, c in enumerate(reversed(pan)):
        d = int(c) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    assert len(pan) == 16 and pan.startswith("500000") and total % 10 == 0


def test_emitir_cuenta_inexistente_422(client, conns, emision, monkeypatch):
    monkeypatch.setattr(repository, "obtener_cuenta", lambda c, i: None)

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 422 and _code(r) == "CUENTA_NO_ENCONTRADA"
    assert conns.coop.commits == 0


@pytest.mark.parametrize(
    "cuenta", [{**CUENTA, "estado": "Bloqueada"}, {**CUENTA, "estado": "Cerrada"}]
)
def test_emitir_cuenta_no_activa_409(client, conns, emision, monkeypatch, cuenta):
    monkeypatch.setattr(repository, "obtener_cuenta", lambda c, i: cuenta)

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 409 and _code(r) == "CUENTA_NO_ACTIVA"
    assert conns.coop.rollbacks == 1 and conns.coop.commits == 0


def test_emitir_producto_inexistente_422(client, emision, monkeypatch):
    monkeypatch.setattr(repository, "obtener_producto", lambda c, i: None)

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 422 and _code(r) == "PRODUCTO_NO_ENCONTRADO"


@pytest.mark.parametrize(
    "producto",
    [
        {"tipo_producto": "Cuenta", "estado": "A"},
        {"tipo_producto": "Tarjeta", "estado": "I"},
    ],
)
def test_emitir_producto_incorrecto_422(client, emision, monkeypatch, producto):
    monkeypatch.setattr(repository, "obtener_producto", lambda c, i: producto)

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 422 and _code(r) == "PRODUCTO_NO_ES_TARJETA"


def test_emitir_usa_el_subproducto_elegido(client, emision, monkeypatch):
    recibido = {}

    def subproducto(_c, id_producto, id_sub_producto):
        recibido.update(producto=id_producto, sub=id_sub_producto)
        return {
            **SUBPRODUCTO,
            "id_sub_producto": 6,
            "codigo_sub_producto": "TCR001-MC",
            "codigo_bin": "510000",
        }

    monkeypatch.setattr(repository, "obtener_subproducto_con_bin", subproducto)

    r = client.post(
        BASE, json={**PAYLOAD, "idSubProducto": 6, "tipoTarjeta": "Credito"}
    )

    assert r.status_code == 201
    assert recibido == {"producto": 4, "sub": 6}
    assert emision["tarjeta"]["id_sub_producto"] == 6
    assert emision["tarjeta"]["id_bin"] == 1


def test_emitir_subproducto_inexistente_o_de_otro_producto_422(
    client, emision, monkeypatch
):
    monkeypatch.setattr(repository, "obtener_subproducto_con_bin", lambda c, i, s: None)

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 422 and _code(r) == "SUBPRODUCTO_NO_ENCONTRADO"


@pytest.mark.parametrize(
    "cambio",
    [{"estado": "I"}, {"id_bin": None, "estado_bin": None}, {"estado_bin": "I"}],
)
def test_emitir_subproducto_sin_bin_activo_422(client, emision, monkeypatch, cambio):
    monkeypatch.setattr(
        repository,
        "obtener_subproducto_con_bin",
        lambda c, i, s: {**SUBPRODUCTO, **cambio},
    )

    r = client.post(BASE, json=PAYLOAD)

    assert r.status_code == 422 and _code(r) == "BIN_INVALIDO"


@pytest.mark.parametrize(
    ("tipo", "codigo"),
    [("Credito", "TDB001-MC"), ("Debito", "TCR001-MC"), ("Debito", "XYZ001")],
)
def test_emitir_tipo_que_no_corresponde_al_subproducto_422(
    client, conns, emision, monkeypatch, tipo, codigo
):
    monkeypatch.setattr(
        repository,
        "obtener_subproducto_con_bin",
        lambda c, i, s: {**SUBPRODUCTO, "codigo_sub_producto": codigo},
    )

    r = client.post(BASE, json={**PAYLOAD, "tipoTarjeta": tipo})

    assert r.status_code == 422 and _code(r) == "TIPO_TARJETA_NO_COINCIDE"
    assert "tarjeta" not in emision and conns.coop.commits == 0


@pytest.mark.parametrize(("largo", "status"), [(26, 201), (27, 400)])
def test_emitir_nombre_impreso_hasta_26_caracteres(client, emision, largo, status):
    r = client.post(BASE, json={**PAYLOAD, "nombreTarjeta": "A" * largo})

    assert r.status_code == status


def test_emitir_sin_subproducto_400(client, emision):
    cuerpo = {k: v for k, v in PAYLOAD.items() if k != "idSubProducto"}

    assert client.post(BASE, json=cuerpo).status_code == 400


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


def test_emitir_extension_con_titular_inexistente_422(client, emision, monkeypatch):
    monkeypatch.setattr(repository, "obtener_titular", lambda c, i: None)

    r = client.post(BASE, json={**PAYLOAD, "esExtension": True, "idTarjetaTitular": 9})

    assert r.status_code == 422 and _code(r) == "TARJETA_TITULAR_NO_ENCONTRADA"


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
    assert item["esExtension"] is False and item["idTarjetaTitular"] is None
    assert llamada["args"] == (4, None, "Generada", "fechaEmision", "asc", 1, 20, None)


@pytest.mark.parametrize(("valor", "esperado"), [("false", False), ("true", True)])
def test_buscar_filtra_por_extension(client, monkeypatch, valor, esperado):
    llamada = _lista(monkeypatch)

    r = client.get(BASE, params={"idCuenta": 4, "esExtension": valor})

    assert r.status_code == 200
    assert llamada["args"][-1] is esperado


@pytest.mark.parametrize(
    "params",
    [
        {"pageSize": 101},
        {"pageSize": 0},
        {"page": 0},
        {"estado": "NoExiste"},
        {"idCliente": "abc"},
        {"esExtension": "quizas"},
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
    capturado: dict[str, Any] = {"historiales": []}
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda c, i, **k: fila)
    monkeypatch.setattr(repository, "existe_transicion", lambda c, o, d: transicion)

    def actualizar(_c, _i, estado, **marcas):
        capturado["estado"] = estado
        capturado["marcas"] = marcas

    def historial(*a):
        capturado["historial"] = a
        capturado["historiales"].append(a)

    monkeypatch.setattr(repository, "actualizar_estado", actualizar)
    monkeypatch.setattr(repository, "insertar_historial", historial)
    return capturado


@pytest.mark.parametrize(
    ("anterior", "destino", "evento", "marcas"),
    [
        ("Solicitada", "Anulada", "Anulacion", {"resolucion": True}),
        ("Aprobada", "Generada", "CambioEstado", {"emision": True}),
        ("Activa", "Bloqueada", "Bloqueo", {}),
        ("Bloqueada", "Activa", "Desbloqueo", {}),
        ("Generada", "Anulada", "Anulacion", {}),
        ("Activa", "Cancelada", "CambioEstado", {}),
        ("Activa", "Vencida", "CambioEstado", {}),
        ("Vencida", "Cerrada", "CambioEstado", {}),
    ],
)
def test_estado_valido_200_registra_historial_y_fechas(
    client, conns, monkeypatch, anterior, destino, evento, marcas
):
    capturado = _estado(
        monkeypatch, {**FILA, "estado_actual": anterior, "pin_asignado": True}
    )

    r = client.post(
        f"{BASE}/301/estado", json={"estado": destino, "motivo": " Motivo "}
    )

    assert r.status_code == 200
    assert capturado["estado"] == destino
    esperado = {"resolucion": False, "emision": False, "pin_asignado": False}
    assert capturado["marcas"] == {**esperado, **marcas}
    assert capturado["historial"][2:6] == (evento, anterior, destino, "Motivo")
    assert capturado["historial"][7] == "testclient"
    assert conns.coop.commits == 1 and conns.seg.commits == 0


@pytest.mark.parametrize(("tipo", "temporal"), [("Debito", True), ("Credito", False)])
def test_aprobar_genera_pin_automatico_sin_exponerlo(
    client, conns, monkeypatch, seg, caplog, tipo, temporal
):
    capturado = _estado(monkeypatch, {**FILA, "tipo_tarjeta": tipo})
    seg.custodiar()
    caplog.set_level(logging.DEBUG)

    r = client.post(
        f"{BASE}/301/estado", json={"estado": "Aprobada", "motivo": "Aprobada"}
    )

    assert r.status_code == 200
    assert capturado["marcas"] == {
        "resolucion": True,
        "emision": False,
        "pin_asignado": True,
    }
    fila = seg.pin()
    assert fila["estado"] == "Activo" and fila["requiere_cambio"] is temporal
    # El Offset verifica un PIN no trivial que eligió el HSM, y solo ese
    pin = pin_generado(seg)
    assert not es_pin_debil(pin)
    assert pin_valido(seg, pin)
    assert not pin_valido(seg, f"{(int(pin) + 1) % 10000:04d}")
    eventos = [h[2] for h in capturado["historiales"]]
    assert eventos == ["CambioEstado", "CambioPin"]
    assert capturado["historiales"][1][5] == "PIN generado automáticamente"
    for secreto in (pin, fila["offset"], PAN):
        assert secreto not in r.text and secreto not in caplog.text
        assert secreto not in str(capturado["historiales"])
    # SeguridadDB confirma el Offset antes que CooperativaDB el estado
    assert conns.seg.commits == 1 and conns.coop.commits == 1


def test_aprobar_sin_pan_custodiado_503_sin_cambiar_estado(client, conns, monkeypatch):
    capturado = _estado(monkeypatch, FILA)

    r = client.post(f"{BASE}/301/estado", json={"estado": "Aprobada", "motivo": "x"})

    assert r.status_code == 503 and _code(r) == "PAN_NO_DISPONIBLE"
    assert "estado" not in capturado and conns.coop.commits == 0


def test_aprobar_sin_hsm_503_sin_cambiar_estado(client, conns, monkeypatch, seg):
    capturado = _estado(monkeypatch, FILA)
    seg.custodiar()

    def sin_hsm():
        raise HsmNoDisponible("x")

    monkeypatch.setattr(service, "obtener_hsm", sin_hsm)

    r = client.post(f"{BASE}/301/estado", json={"estado": "Aprobada", "motivo": "x"})

    assert r.status_code == 503 and _code(r) == "HSM_NO_DISPONIBLE"
    assert "estado" not in capturado and seg.pines == {}


def test_aprobar_si_falla_cooperativa_la_tarjeta_sigue_solicitada_y_se_reintenta(
    client, conns, monkeypatch, seg
):
    capturado = _estado(monkeypatch, FILA)
    seg.custodiar()
    conns.coop.falla_commit = DBAPIError("COMMIT", {}, Exception("caida"))

    r = client.post(f"{BASE}/301/estado", json={"estado": "Aprobada", "motivo": "x"})

    assert r.status_code == 500 and _code(r) == "ERROR_INTERNO"
    assert conns.coop.rollbacks == 1
    primer_offset = seg.pin()["offset"]

    conns.coop.falla_commit = None
    capturado.clear()
    capturado["historiales"] = []
    r = client.post(f"{BASE}/301/estado", json={"estado": "Aprobada", "motivo": "x"})

    assert r.status_code == 200
    # El reintento genera un PIN nuevo que reemplaza al anterior
    assert pin_valido(seg, pin_generado(seg))
    assert len(primer_offset) == 4


def test_generada_a_activa_a_mano_409_activacion_automatica(client, conns, monkeypatch):
    capturado = _estado(
        monkeypatch, {**FILA, "estado_actual": "Generada", "pin_asignado": True}
    )

    r = client.post(f"{BASE}/301/estado", json={"estado": "Activa", "motivo": "x"})

    assert r.status_code == 409 and _code(r) == "ACTIVACION_AUTOMATICA"
    assert "estado" not in capturado and conns.coop.commits == 0


def test_estado_transicion_invalida_409(client, conns, monkeypatch):
    capturado = _estado(monkeypatch, FILA, transicion=False)

    r = client.post(f"{BASE}/301/estado", json={"estado": "Bloqueada", "motivo": "x"})

    assert r.status_code == 409 and _code(r) == "TRANSICION_INVALIDA"
    assert "estado" not in capturado and conns.coop.commits == 0


def test_reactivar_sin_pin_409(client, monkeypatch):
    capturado = _estado(monkeypatch, {**FILA, "estado_actual": "Bloqueada"})

    r = client.post(f"{BASE}/301/estado", json={"estado": "Activa", "motivo": "x"})

    assert r.status_code == 409 and _code(r) == "PIN_NO_ASIGNADO"
    assert "estado" not in capturado


def test_estado_inexistente_404(client, monkeypatch):
    _estado(monkeypatch, None)

    r = client.post(f"{BASE}/9/estado", json={"estado": "Activa", "motivo": "x"})

    assert r.status_code == 404


def test_estado_trigger_52005_409_sin_filtrar_sql(client, conns, monkeypatch):
    _estado(monkeypatch, {**FILA, "estado_actual": "Bloqueada", "pin_asignado": True})

    def falla(*_a, **_k):
        raise _error_db("[SQL Server]Cambio no permitido (52005) (SQLExecDirectW)")

    monkeypatch.setattr(repository, "actualizar_estado", falla)

    r = client.post(f"{BASE}/301/estado", json={"estado": "Activa", "motivo": "x"})

    assert r.status_code == 409 and _code(r) == "TRANSICION_INVALIDA"
    assert "SQL" not in r.text and "SECRETO" not in r.text
    assert conns.coop.rollbacks == 1


@pytest.mark.parametrize(
    "body",
    [
        {"estado": "Activa"},
        {"estado": "Activa", "motivo": "   "},
        # Solicitada solo es el estado inicial; los demás ya no existen
        {"estado": "Solicitada", "motivo": "x"},
        {"estado": "EnRevision", "motivo": "x"},
        {"estado": "Rechazada", "motivo": "x"},
        {"estado": "Pendiente", "motivo": "x"},
        {"estado": "Activa", "motivo": "x" * 501},
        {"estado": "Activa", "motivo": "x", "pinAsignado": True},
    ],
)
def test_estado_body_invalido_400(client, body):
    assert client.post(f"{BASE}/301/estado", json=body).status_code == 400


# TAR-05


def _pin(monkeypatch, seg, fila=None, custodiar=True):
    capturado: dict[str, Any] = {"marcado": False}
    fila = {**FILA, "estado_actual": "Activa", "pin_asignado": True} | (fila or {})
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda c, i, **k: fila)
    monkeypatch.setattr(
        repository,
        "marcar_pin_asignado",
        lambda c, i: capturado.__setitem__("marcado", True),
    )
    monkeypatch.setattr(
        repository,
        "insertar_historial",
        lambda *a: capturado.__setitem__("historial", a),
    )
    if custodiar:
        seg.custodiar()
    return capturado


@pytest.mark.parametrize(("tipo", "temporal"), [("Debito", True), ("Credito", False)])
def test_regenerar_pin_204_reemplaza_offset_y_desbloquea(
    client, conns, monkeypatch, seg, tipo, temporal
):
    capturado = _pin(monkeypatch, seg, {"tipo_tarjeta": tipo})
    seg.pines[301] = {
        "offset": "1111",
        "pvk": "x",
        "requiere_cambio": False,
        "estado": "Bloqueado",
        "intentos": 3,
    }

    r = client.post(f"{BASE}/301/pin")

    assert r.status_code == 204 and r.content == b""
    fila = seg.pin()
    assert fila["offset"] != "1111" and fila["estado"] == "Activo"
    assert fila["intentos"] == 0 and fila["requiere_cambio"] is temporal
    assert pin_valido(seg, pin_generado(seg))
    assert capturado["marcado"]
    assert capturado["historial"][2] == "CambioPin"
    assert capturado["historial"][5] == "Regeneración de PIN"
    assert conns.seg.commits == 1 and conns.coop.commits == 1


@pytest.mark.parametrize(
    "estado", ["Aprobada", "Generada", "Activa", "Inactiva", "Bloqueada"]
)
def test_regenerar_pin_en_estados_permitidos(client, monkeypatch, seg, estado):
    _pin(monkeypatch, seg, {"estado_actual": estado})

    assert client.post(f"{BASE}/301/pin").status_code == 204


@pytest.mark.parametrize(
    "estado", ["Solicitada", "Cancelada", "Anulada", "Vencida", "Cerrada"]
)
def test_regenerar_pin_estado_no_permitido_409(client, conns, monkeypatch, seg, estado):
    _pin(monkeypatch, seg, {"estado_actual": estado})

    r = client.post(f"{BASE}/301/pin")

    assert r.status_code == 409 and _code(r) == "PIN_NO_PERMITIDO"
    assert seg.pines == {} and conns.coop.commits == 0


def test_regenerar_pin_tarjeta_inexistente_404(client, monkeypatch, seg):
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda c, i, **k: None)

    assert client.post(f"{BASE}/9/pin").status_code == 404


@pytest.mark.parametrize(
    "contenido",
    [
        b'{"pin": "7392"}',
        b'{"encryptedPinBlock": "00112233445566778899AABBCCDDEEFF", "keyReference": "k"}',
        b"{}",
        b"7392",
    ],
)
def test_regenerar_pin_con_body_400_nunca_repite_el_valor(
    client, monkeypatch, seg, contenido
):
    _pin(monkeypatch, seg)

    r = client.post(
        f"{BASE}/301/pin",
        content=contenido,
        headers={"content-type": "application/json"},
    )

    assert r.status_code == 400 and _code(r) == "DATOS_INVALIDOS"
    assert "7392" not in r.text and "0011223344" not in r.text
    assert seg.pines == {}


def test_regenerar_pin_sin_pan_custodiado_503(client, monkeypatch, seg):
    _pin(monkeypatch, seg, custodiar=False)

    r = client.post(f"{BASE}/301/pin")

    assert r.status_code == 503 and _code(r) == "PAN_NO_DISPONIBLE"


def test_regenerar_pin_sin_hsm_503(client, monkeypatch, seg):
    _pin(monkeypatch, seg)

    def sin_hsm():
        raise HsmNoDisponible("x")

    monkeypatch.setattr(service, "obtener_hsm", sin_hsm)

    r = client.post(f"{BASE}/301/pin")

    assert r.status_code == 503 and _code(r) == "HSM_NO_DISPONIBLE"
    assert seg.pines == {}


def test_regenerar_pin_falla_cooperativa_503_pero_el_pin_nuevo_rige(
    client, conns, monkeypatch, seg
):
    _pin(monkeypatch, seg)
    conns.coop.falla_commit = DBAPIError("COMMIT", {}, Exception("caida"))

    r = client.post(f"{BASE}/301/pin")

    assert r.status_code == 503 and _code(r) == "PIN_ASIGNACION_NO_CONFIRMADA"
    assert conns.seg.commits == 1 and conns.coop.rollbacks == 1
    assert pin_valido(seg, pin_generado(seg))


def test_regenerar_pin_ni_pin_ni_offset_aparecen_en_logs(
    client, monkeypatch, seg, caplog
):
    _pin(monkeypatch, seg)
    caplog.set_level(logging.DEBUG)

    r = client.post(f"{BASE}/301/pin")

    assert r.status_code == 204
    for secreto in (pin_generado(seg), seg.pin()["offset"], PAN):
        assert secreto not in caplog.text and secreto not in r.text


def test_regenerar_pin_fallo_de_bd_revierte_ambas_y_no_filtra_nada(
    client, conns, monkeypatch, seg, caplog
):
    _pin(monkeypatch, seg)
    caplog.set_level(logging.DEBUG)

    def falla(*_a, **_k):
        raise DBAPIError("UPDATE x", {"offset": "SECRETO"}, Exception("caida"))

    monkeypatch.setattr(repository, "guardar_pin_generado", falla)

    r = client.post(f"{BASE}/301/pin")

    assert r.status_code == 500 and _code(r) == "ERROR_INTERNO"
    assert conns.coop.rollbacks >= 1 and conns.seg.rollbacks >= 1
    assert conns.coop.commits == 0 and conns.seg.commits == 0
    for texto in (r.text, caplog.text):
        assert "SECRETO" not in texto and "UPDATE" not in texto


@pytest.mark.parametrize("pin", ["1235", "2580", "1212", "7392", "0001"])
def test_pin_no_trivial_es_aceptado(pin):
    assert es_pin_debil(pin) is False


# PIN pad simulado (solo fuera de producción)

PIN_BLOCK = "/api/v1/pruebas/pin-block"


def test_pin_block_prueba_arma_un_bloque_que_verifica_el_offset(
    client, monkeypatch, seg
):
    _pin(monkeypatch, seg)
    monkeypatch.setattr(repository, "existe_tarjeta", lambda c, i: True)
    assert client.post(f"{BASE}/301/pin").status_code == 204
    pin = pin_generado(seg)

    r = client.post(PIN_BLOCK, json={"idTarjeta": 301, "pin": pin})

    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo) == {"encryptedPinBlock", "keyReference"}
    assert pin not in r.text and PAN not in r.text
    # Es el bloque que ATM-01 verifica contra el Offset guardado
    fila = seg.pin()
    assert HSM.verificar_pin(
        cuerpo["encryptedPinBlock"],
        cuerpo["keyReference"],
        PAN,
        fila["offset"],
        fila["pvk"],
    )


def test_pin_block_prueba_tarjeta_inexistente_404(client, monkeypatch, seg):
    monkeypatch.setattr(repository, "existe_tarjeta", lambda c, i: False)

    r = client.post(PIN_BLOCK, json={"idTarjeta": 9, "pin": "7392"})

    assert r.status_code == 404


def test_pin_block_prueba_sin_pan_503(client, monkeypatch, seg):
    monkeypatch.setattr(repository, "existe_tarjeta", lambda c, i: True)

    r = client.post(PIN_BLOCK, json={"idTarjeta": 301, "pin": "7392"})

    assert r.status_code == 503 and _code(r) == "PAN_NO_DISPONIBLE"


@pytest.mark.parametrize(
    "body",
    [
        {"idTarjeta": 301, "pin": "73"},
        {"idTarjeta": 301, "pin": 7392},
        {"idTarjeta": "301", "pin": "7392"},
        {"idTarjeta": 0, "pin": "7392"},
        {"idTarjeta": True, "pin": "7392"},
        {"pin": "7392"},
        {"idTarjeta": 301, "pin": "7392", "x": 1},
    ],
)
def test_pin_block_prueba_body_invalido_400_sin_repetir_el_pin(client, seg, body):
    r = client.post(PIN_BLOCK, json=body)

    assert r.status_code == 400 and _code(r) == "PIN_INVALIDO"
    assert "7392" not in r.text


def test_pin_block_prueba_no_existe_en_produccion(client, monkeypatch, seg):
    monkeypatch.setattr(
        router, "get_settings", lambda: SimpleNamespace(app_env="production")
    )

    r = client.post(PIN_BLOCK, json={"idTarjeta": 301, "pin": "7392"})

    assert r.status_code == 404 and "7392" not in r.text


def test_pin_block_prueba_solo_admin(conns, seg):
    simular_sesion(app, usuario_con_roles("ASESOR", "SUPERVISOR"))

    r = _llamar(conns, "post", PIN_BLOCK, {"idTarjeta": 301, "pin": "7392"})

    assert r.status_code == 403 and _code(r) == "SIN_PERMISO"


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


# Roles de cada tarea TAR (GitHubProject_Files)
_RUTAS_Y_ROLES = [
    ("post", BASE, PAYLOAD, ("ASESOR", "ADMIN")),
    ("get", BASE, None, ("ASESOR", "SUPERVISOR", "ADMIN")),
    ("get", f"{BASE}/1", None, ("ASESOR", "SUPERVISOR", "ADMIN")),
    (
        "post",
        f"{BASE}/1/estado",
        {"estado": "Activa", "motivo": "x"},
        ("ASESOR", "SUPERVISOR", "ADMIN"),
    ),
    ("post", f"{BASE}/1/pin", None, ("ASESOR", "ADMIN")),
    ("get", f"{BASE}/1/historial", None, ("SUPERVISOR", "AUDITOR", "ADMIN")),
]


def _llamar(conns, metodo, ruta, body):
    app.dependency_overrides[cooperativa] = lambda: conns.coop
    app.dependency_overrides[router.seguridad] = lambda: conns.seg
    try:
        return getattr(TestClient(app), metodo)(
            ruta, **({"json": body} if body is not None else {})
        )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(("metodo", "ruta", "body", "_roles"), _RUTAS_Y_ROLES)
def test_sin_sesion_401_y_se_audita(
    conns, eventos_auditados, metodo, ruta, body, _roles
):
    r = _llamar(conns, metodo, ruta, body)

    assert r.status_code == 401 and _code(r) == "NO_AUTENTICADO"
    assert [e.accion for e in eventos_auditados] == ["ACCESO_DENEGADO"]


@pytest.mark.parametrize(("metodo", "ruta", "body", "roles"), _RUTAS_Y_ROLES)
def test_rol_sin_permiso_403(conns, metodo, ruta, body, roles):
    simular_sesion(app, usuario_con_roles(*(r for r in ROLES if r not in roles)))

    r = _llamar(conns, metodo, ruta, body)

    assert r.status_code == 403 and _code(r) == "SIN_PERMISO"


def test_openapi_documenta_las_seis_rutas_y_el_pin_sin_body():
    rutas = app.openapi()["paths"]

    assert set(rutas[BASE]) == {"post", "get"}
    assert "get" in rutas[f"{BASE}/{{idTarjeta}}"]
    assert "post" in rutas[f"{BASE}/{{idTarjeta}}/estado"]
    assert "get" in rutas[f"{BASE}/{{idTarjeta}}/historial"]
    # TAR-05: el PIN lo genera el HSM; el cliente nunca lo envía
    assert "requestBody" not in rutas[f"{BASE}/{{idTarjeta}}/pin"]["post"]
    assert "post" in rutas["/api/v1/pruebas/pin-block"]

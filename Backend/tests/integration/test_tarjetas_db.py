"""TAR-01..06 contra las bases reales.

Se omiten si no hay BD configurada, como en el CI. Cada prueba usa una transacción por
base que se revierte al final; commit no hace nada.
"""

import re
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import traducir_error_bd
from app.core.config.settings import get_settings
from app.core.database.db import cooperativa, get_engine
from app.core.security import audit
from app.main import app
from app.modules.tarjetas import repository, router
from tests.sesion import ID_AUDITORIA, simular_sesion

pytestmark = pytest.mark.skipif(
    not get_settings().cooperativa_db_server,
    reason="CooperativaDB no configurada",
)

BASE = "/api/v1/tarjetas"
PIN = "7392"


def _pin(client: TestClient, id_tarjeta: int, pin: str) -> dict[str, Any]:
    """Body de TAR-05 armado por el PIN pad simulado (HSM con las claves del .env)."""
    r = client.post(
        "/api/v1/pruebas/pin-block", json={"idTarjeta": id_tarjeta, "pin": pin}
    )
    assert r.status_code == 200, r.text
    return r.json()


class _SinCommit:
    """Conexión real con commit y rollback anulados; el fixture bd revierte al final."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._conn, nombre)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


@pytest.fixture()
def bd() -> Iterator[tuple[Connection, Connection]]:
    with (
        get_engine("cooperativa").connect() as coop,
        get_engine("seguridad").connect() as seg,
    ):
        yield coop, seg
        coop.rollback()
        seg.rollback()


@pytest.fixture()
def client(bd) -> Iterator[TestClient]:
    coop, seg = bd
    app.dependency_overrides[cooperativa] = lambda: _SinCommit(coop)
    app.dependency_overrides[router.seguridad] = lambda: _SinCommit(seg)
    simular_sesion(app)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def datos(bd) -> dict[str, int]:
    coop, _ = bd
    id_cuenta = coop.execute(
        text("SELECT TOP 1 IdCuenta FROM Cuentas.Cuenta WHERE Estado = 'Activa'")
    ).scalar_one()
    id_producto = coop.execute(
        text(
            """
            SELECT TOP 1 p.IdProducto
            FROM ProductosFinancieros.Producto AS p
            JOIN ProductosFinancieros.SubProducto AS s ON s.IdProducto = p.IdProducto
            WHERE p.TipoProducto = 'Tarjeta' AND p.Estado = 'A' AND s.IdBIN IS NOT NULL
            """
        )
    ).scalar_one()
    return {"idCuenta": id_cuenta, "idProducto": id_producto}


def _emitir(client: TestClient, datos: dict[str, int], **extra: Any) -> dict[str, Any]:
    r = client.post(
        BASE,
        json={
            **datos,
            "tipoTarjeta": "Debito",
            "nombreTarjeta": "PRUEBA INTEGRACION",
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_auditoria_real_registra_exito_y_fallo(client, bd, datos, monkeypatch):
    _, seg = bd
    monkeypatch.setattr(audit, "_persistir", lambda e: audit._insertar(seg, e))

    id_tarjeta = _emitir(client, datos)["idTarjeta"]
    ruta = f"{BASE}/{id_tarjeta}"
    assert client.post(f"{ruta}/pin", json=_pin(client, id_tarjeta, "1234")).status_code == 422
    assert client.post(f"{ruta}/pin", json=_pin(client, id_tarjeta, PIN)).status_code == 204

    filas = seg.execute(
        text(
            """
            SELECT UsuarioID, NombreAccion, TablaAfectada, DireccionIP, Descripcion,
                   Resultado
            FROM Auditoria.Auditoria
            WHERE IDRegistro = :i AND TablaAfectada = 'Tarjeta.Tarjeta'
            ORDER BY AuditoriaID
            """
        ),
        {"i": str(id_tarjeta)},
    ).all()
    assert [(f[1], f[5]) for f in filas] == [
        ("INSERT", "Exitoso"),
        ("UPDATE", "Fallido"),
        ("UPDATE", "Exitoso"),
    ]
    assert filas[1][4].endswith("PIN_DEBIL")
    assert all(f[0] == ID_AUDITORIA and f[3] == "testclient" for f in filas)
    assert PIN not in str(filas) and "1234" not in str(filas)


def test_emision_guarda_solo_token_mascara_y_hash(client, bd, datos):
    coop, _ = bd
    tarjeta = _emitir(client, datos)

    fila = coop.execute(
        text(
            """
            SELECT Estado, PinAsignado, NumeroEnmascarado, DATALENGTH(HashNumeroTarjeta),
                   DATEDIFF(year, FechaEmision, FechaExpiracion), IdSubProducto, IdBIN
            FROM Tarjeta.Tarjeta WHERE IdTarjeta = :i
            """
        ),
        {"i": tarjeta["idTarjeta"]},
    ).one()
    assert fila[0] == "Generada" and fila[1] is False
    assert fila[2] == tarjeta["numeroEnmascarado"] and "*" in fila[2]
    assert fila[3] == 32 and fila[4] == 5
    assert tarjeta["estadoActual"] == "Generada"
    assert tarjeta["tokenTarjeta"].startswith("tok_")


def test_emision_con_envio_y_extension(client, bd, datos):
    coop, _ = bd
    titular = _emitir(client, datos)
    extension = _emitir(
        client,
        datos,
        esExtension=True,
        idTarjetaTitular=titular["idTarjeta"],
        requiereEnvio=True,
        direccionEnvio="Av. de Prueba 123",
        idCiudadEnvio=1,
    )

    envio = coop.execute(
        text(
            """
            SELECT Estado, DireccionEnvio, IdCiudad FROM Tarjeta.EnviosTarjeta
            WHERE IdTarjeta = :i
            """
        ),
        {"i": extension["idTarjeta"]},
    ).one()
    assert tuple(envio) == ("PENDIENTE", "Av. de Prueba 123", 1)


def test_emision_extension_con_titular_inexistente_422(client, datos):
    r = client.post(
        BASE,
        json={
            **datos,
            "tipoTarjeta": "Debito",
            "nombreTarjeta": "X",
            "esExtension": True,
            "idTarjetaTitular": 2_000_000_000,
        },
    )

    assert r.status_code == 422
    assert r.json()["code"] == "TARJETA_TITULAR_NO_ENCONTRADA"


def test_emision_producto_que_no_es_tarjeta_422(client, datos):
    r = client.post(
        BASE,
        json={
            **datos,
            "idProducto": 1,
            "tipoTarjeta": "Debito",
            "nombreTarjeta": "X",
        },
    )

    assert r.status_code == 422
    assert r.json()["code"] == "PRODUCTO_NO_ES_TARJETA"


def test_emision_cuenta_inexistente_422(client, datos):
    r = client.post(
        BASE,
        json={
            **datos,
            "idCuenta": 2_000_000_000,
            "tipoTarjeta": "Debito",
            "nombreTarjeta": "X",
        },
    )

    assert r.status_code == 422
    assert r.json()["code"] == "CUENTA_NO_ENCONTRADA"


def test_ciclo_completo_pin_activacion_bloqueo_e_historial(client, bd, datos):
    coop, seg = bd
    id_tarjeta = _emitir(client, datos)["idTarjeta"]
    ruta = f"{BASE}/{id_tarjeta}"

    # Activar sin PIN se rechaza
    r = client.post(f"{ruta}/estado", json={"estado": "Activa", "motivo": "x"})
    assert r.status_code == 409
    assert r.json()["code"] == "PIN_NO_ASIGNADO"

    # PIN débil y asignación correcta
    assert client.post(f"{ruta}/pin", json=_pin(client, id_tarjeta, "1234")).status_code == 422
    assert client.post(f"{ruta}/pin", json=_pin(client, id_tarjeta, PIN)).status_code == 204

    guardado = seg.execute(
        text(
            """
            SELECT PINOffset, ReferenciaClavePVK, TienePINAsignado, Estado
            FROM Tarjetas.TarjetaPIN
            WHERE ID_Tarjeta = :i
            """
        ),
        {"i": id_tarjeta},
    ).one()
    # IBM 3624: solo el Offset de 4 dígitos y la referencia de la PVK, nunca el PIN
    assert len(guardado[0]) == 4 and guardado[0].isdigit() and guardado[0] != PIN
    assert guardado[1] == "SIM-PVK-01"
    assert guardado[2] is True and guardado[3] == "Activo"
    # El PAN ficticio quedó custodiado cifrado en el repositorio de pruebas
    custodia = seg.execute(
        text("SELECT ReferenciaClave FROM Pruebas.PanFicticio WHERE IdTarjeta = :i"),
        {"i": id_tarjeta},
    ).one()
    assert custodia[0] == "SIM-PAN-01"

    # El PIN se asigna una sola vez
    r = client.post(f"{ruta}/pin", json=_pin(client, id_tarjeta, "2580"))
    assert r.status_code == 409 and r.json()["code"] == "PIN_YA_ASIGNADO"

    # Transiciones válidas, inválida y desbloqueo
    for destino, esperado in [
        ("Activa", 200),
        ("Bloqueada", 200),
        ("Generada", 409),
        ("Activa", 200),
        ("Cancelada", 200),
        ("Activa", 409),
    ]:
        r = client.post(
            f"{ruta}/estado", json={"estado": destino, "motivo": f"A {destino}"}
        )
        assert r.status_code == esperado, (destino, r.text)

    # La cuenta no se toca al bloquear la tarjeta
    estado_cuenta = coop.execute(
        text("SELECT Estado FROM Cuentas.Cuenta WHERE IdCuenta = :i"),
        {"i": datos["idCuenta"]},
    ).scalar_one()
    assert estado_cuenta == "Activa"

    # Historial: más reciente primero y sin el PIN
    r = client.get(f"{ruta}/historial", params={"sort": "idHistorial,desc"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["total"] == 6
    tipos = [item["tipoEvento"] for item in cuerpo["items"]]
    assert tipos == [
        "CambioEstado",
        "Desbloqueo",
        "Bloqueo",
        "Activacion",
        "CambioPin",
        "CambioEstado",
    ]
    assert cuerpo["items"][0]["motivo"] == "A Cancelada"
    assert cuerpo["items"][0]["fechaCambio"].endswith("-05:00")
    assert PIN not in r.text

    fila = coop.execute(
        text(
            """
            SELECT TOP 1 RealizadoPor, IdCanal, DireccionIP FROM Tarjeta.TarjetaHis
            WHERE IdTarjeta = :i ORDER BY IdHistorial DESC
            """
        ),
        {"i": id_tarjeta},
    ).one()
    assert fila[1] is not None and fila[2] == "testclient"


def test_busqueda_filtros_paginacion_y_orden(client, datos):
    primera = _emitir(client, datos)
    segunda = _emitir(client, datos)

    r = client.get(
        BASE,
        params={
            "idCuenta": datos["idCuenta"],
            "estado": "Generada",
            "pageSize": 1,
            "sort": "idTarjeta,desc",
        },
    )

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["total"] >= 2 and cuerpo["pageSize"] == 1
    assert [i["idTarjeta"] for i in cuerpo["items"]] == [segunda["idTarjeta"]]
    assert "tokenTarjeta" not in cuerpo["items"][0]

    r = client.get(
        BASE,
        params={
            "idCuenta": datos["idCuenta"],
            "estado": "Generada",
            "pageSize": 1,
            "page": 2,
            "sort": "idTarjeta,desc",
        },
    )
    assert r.json()["items"][0]["idTarjeta"] == primera["idTarjeta"]


def test_busqueda_sin_filtros_y_detalle_de_tarjeta_existente(client):
    r = client.get(BASE)
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    id_tarjeta = r.json()["items"][0]["idTarjeta"]
    detalle = client.get(f"{BASE}/{id_tarjeta}")
    assert detalle.status_code == 200
    assert (
        detalle.json()["numeroEnmascarado"].strip()
        == detalle.json()["numeroEnmascarado"]
    )


def test_historial_filtra_por_fechas_inclusivas(client, datos):
    ruta = f"{BASE}/{_emitir(client, datos)['idTarjeta']}/historial"
    fecha = date.fromisoformat(client.get(ruta).json()["items"][0]["fechaCambio"][:10])
    dia = timedelta(days=1)

    def total(desde: date, hasta: date) -> int:
        r = client.get(
            ruta,
            params={"fechaDesde": desde.isoformat(), "fechaHasta": hasta.isoformat()},
        )
        assert r.status_code == 200
        return r.json()["total"]

    assert total(fecha, fecha) == 1
    assert total(fecha - dia, fecha + dia) == 1
    assert total(fecha + dia, fecha + dia) == 0
    assert total(fecha - dia, fecha - dia) == 0


def test_todas_las_tarjetas_usan_el_formato_de_mascara(client):
    r = client.get(BASE, params={"pageSize": 100})

    assert r.status_code == 200
    assert r.json()["items"]
    for item in r.json()["items"]:
        assert re.fullmatch(r"\d{4} \d{2}\*\* \*{4} \d{4}", item["numeroEnmascarado"])


def test_throw_real_52005_se_traduce(client, bd, datos):
    coop, _ = bd
    id_tarjeta = _emitir(client, datos)["idTarjeta"]

    # Salta la validación del servicio para que sea el trigger quien rechace el cambio
    with pytest.raises(DBAPIError) as error:
        repository.actualizar_estado(coop, id_tarjeta, "Cancelada")

    traducido = traducir_error_bd(error.value)
    assert traducido.status_code == 409
    detalle: Any = traducido.detail
    assert detalle["code"] == "TRANSICION_INVALIDA"


def test_respuesta_de_error_real_es_problem_details(client):
    r = client.get(f"{BASE}/2000000000", headers={"X-Request-Id": "req-prueba"})

    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "TARJETA_NO_ENCONTRADA"
    assert r.json()["traceId"] == "req-prueba"


def test_detalle_e_historial_inexistentes_404(client):
    assert client.get(f"{BASE}/2000000000").status_code == 404
    assert client.get(f"{BASE}/2000000000/historial").status_code == 404

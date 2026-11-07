"""Auditoría (F-04) y su uso en las escrituras de tarjetas."""

import logging

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.database.db import cooperativa
from app.core.security import audit
from app.main import app
from app.modules.tarjetas import repository, router
from tests.sesion import ID_AUDITORIA, simular_sesion
from tests.tarjetas_hsm import body_pin, instalar
from tests.unit.test_tarjetas import BASE, FILA, PAYLOAD

EVENTO = audit.EventoAuditoria(
    accion="UPDATE",
    tabla="Tarjeta.Tarjeta",
    id_registro="1",
    resultado="Exitoso",
    usuario=None,
    ip="8.8.8.8",
    descripcion="x" * 600,
)


class _Conn:
    def __init__(self) -> None:
        self.parametros: dict | None = None

    def execute(self, _sql, parametros):
        self.parametros = parametros

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def _cliente(monkeypatch) -> TestClient:
    conn = _Conn()
    app.dependency_overrides[cooperativa] = lambda: conn
    app.dependency_overrides[router.seguridad] = lambda: conn
    simular_sesion(app)
    monkeypatch.setattr(repository, "insertar_historial", lambda *a: None)
    # HSM simulado y SeguridadDB en memoria, con el PAN de la tarjeta 301 custodiado
    instalar(monkeypatch).custodiar()
    return TestClient(app)


def test_insertar_recorta_la_descripcion_a_la_columna():
    conn = _Conn()

    audit._insertar(conn, EVENTO)  # type: ignore[arg-type]

    assert conn.parametros is not None
    assert len(conn.parametros["descripcion"]) == 500
    assert conn.parametros["resultado"] == "Exitoso"


def test_insertar_guarda_los_roles_de_workos():
    from dataclasses import replace

    conn = _Conn()

    audit._insertar(conn, replace(EVENTO, roles="ADMIN"))  # type: ignore[arg-type]

    assert conn.parametros is not None
    assert conn.parametros["roles"] == "ADMIN"


def test_fallo_de_auditoria_no_rompe_ni_filtra_parametros(monkeypatch, caplog):
    def falla(_evento):
        raise SQLAlchemyError("INSERT parametros SECRETO")

    monkeypatch.setattr(audit, "_persistir", falla)
    caplog.set_level(logging.ERROR)

    audit.registrar(EVENTO)

    assert "SQLAlchemyError" in caplog.text
    assert "SECRETO" not in caplog.text


def test_escritura_exitosa_se_audita(monkeypatch, eventos_auditados):
    c = _cliente(monkeypatch)
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda _c, _i, **_k: FILA)
    monkeypatch.setattr(repository, "marcar_pin_asignado", lambda _c, _i: True)
    try:
        r = c.post(f"{BASE}/301/pin", json=body_pin("7392"))
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 204
    evento = eventos_auditados[0]
    assert (evento.accion, evento.id_registro, evento.resultado) == (
        "UPDATE",
        "301",
        "Exitoso",
    )
    assert evento.usuario == ID_AUDITORIA and evento.ip == "testclient"
    assert "7392" not in str(evento)


def test_intento_fallido_se_audita_con_su_codigo(monkeypatch, eventos_auditados):
    c = _cliente(monkeypatch)
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda _c, _i, **_k: FILA)
    try:
        r = c.post(f"{BASE}/301/pin", json=body_pin("1234"))
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 422
    evento = eventos_auditados[0]
    assert evento.resultado == "Fallido"
    assert evento.descripcion.endswith("PIN_DEBIL")
    assert "1234" not in str(evento)


def test_emision_rechazada_se_audita_sin_id(monkeypatch, eventos_auditados):
    c = _cliente(monkeypatch)
    monkeypatch.setattr(repository, "obtener_cuenta", lambda _c, _i: None)
    try:
        c.post(BASE, json=PAYLOAD)
    finally:
        app.dependency_overrides.clear()

    evento = eventos_auditados[0]
    assert (evento.accion, evento.id_registro, evento.resultado) == (
        "INSERT",
        None,
        "Fallido",
    )
    assert evento.descripcion.endswith("CUENTA_NO_ENCONTRADA")


def test_lecturas_no_se_auditan(monkeypatch, eventos_auditados):
    c = _cliente(monkeypatch)
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda _c, _i, **_k: FILA)
    try:
        assert c.get(f"{BASE}/301").status_code == 200
    finally:
        app.dependency_overrides.clear()

    assert eventos_auditados == []

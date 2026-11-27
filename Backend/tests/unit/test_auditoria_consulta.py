"""E8-01 · Consultar la bitácora de auditoría: un caso por criterio de aceptación."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core import csv as csv_tool
from app.core.database.db import cooperativa, seguridad
from app.core.security import audit
from app.main import app
from app.modules.auditoria import repository, service
from tests.sesion import simular_sesion, usuario_con_roles

BASE = "/api/v1/auditoria"


@pytest.fixture
def http() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def _sesion(
    *roles: str,
    agencia: str = "001",
    agencias: tuple[str, ...] | None = None,
    exportar: bool = False,
) -> None:
    usuario = usuario_con_roles(*roles)
    u = replace(usuario, id_agencia=agencia)
    if exportar:
        u = replace(u, permisos=(*u.permisos, csv_tool.PERMISO_EXPORTAR))
    if agencias is not None:
        u = replace(u, id_agencias=agencias)
    simular_sesion(app, u)
    app.dependency_overrides[seguridad] = lambda: MagicMock()
    app.dependency_overrides[cooperativa] = lambda: MagicMock()


def _mock_valor(monkeypatch: Any, dias: int = 31) -> None:
    """Simula el parámetro AUD_RANGO_MAX_DIAS."""
    monkeypatch.setattr(service.general, "valor", lambda conn, clave, fecha: dias)


def _evento_fila(**kw: Any) -> dict[str, Any]:
    """Fila base como la devolvería el repositorio."""
    base: dict[str, Any] = {
        "AuditoriaID": 100,
        "IdEvento": "aaa-bbb-ccc",
        "CodigoEvento": "EDITAR_ENTIDAD",
        "Modulo": "organizacion",
        "Severidad": "Informativo",
        "FechaHoraUTC": datetime(2026, 11, 20, 18, 0, tzinfo=UTC),
        "FechaHora": datetime(2026, 11, 20, 13, 0),
        "UsuarioID": 1,
        "NombreUsuario": "Admin Prueba",
        "IdAgencia": "001",
        "Canal": "API",
        "DireccionIP": "10.0.0.1",
        "Resultado": "Exitoso",
        "TipoObjetivo": "Organizacion.Agencia",
        "IdObjetivo": "5",
        "IdCorrelacion": "corr-123",
        "Descripcion": "cambio de dirección",
        "FormatoAnterior": False,
        "Cambios": None,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# AC1 · Detalle de evento de cliente: cambios enmascarados
# ---------------------------------------------------------------------------


def test_detalle_cliente_cambios_enmascarados(http, monkeypatch):
    """Cambio de apellido del cliente: antes/después se enmascaran."""
    _sesion("ADMIN")
    _mock_valor(monkeypatch)

    fila = _evento_fila(
        TipoObjetivo="Clientes.Cliente",
        Cambios='{"antes":{"apellido":"López","estado":"Activo"},'
        '"despues":{"apellido":"García","estado":"Activo"}}',
    )
    monkeypatch.setattr(repository, "obtener_evento", lambda c, i: fila)
    monkeypatch.setattr(
        repository,
        "obtener_aprobacion",
        lambda c, i: {
            "IdSolicitud": 1,
            "CodigoTransaccion": "CLI_EDICION",
            "Estado": "Ejecutada",
            "NombreSolicitante": "Ana López",
            "IdInternoSolicitante": 2,
            "FechaSolicitud": datetime(2026, 11, 20, 18, 0, tzinfo=UTC),
            "NombreResolutor": "Carlos Ruiz",
            "IdInternoResolutor": 3,
            "FechaResolucion": datetime(2026, 11, 20, 18, 5, tzinfo=UTC),
        },
    )
    monkeypatch.setattr(repository, "obtener_relacionados", lambda *a: [])

    r = http.get(f"{BASE}/eventos/100")
    assert r.status_code == 200
    body = r.json()
    # El apellido está enmascarado
    assert body["cambios"]["antes"]["apellido"] == "L****"
    assert body["cambios"]["despues"]["apellido"] == "G*****"
    # El estado no se enmascara
    assert body["cambios"]["antes"]["estado"] == "Activo"
    # Aprobación presente
    assert body["aprobacion"]["solicitante"]["nombre"] == "Ana López"
    assert body["aprobacion"]["aprobador"]["nombre"] == "Carlos Ruiz"


# ---------------------------------------------------------------------------
# AC2 · Detalle de agencia/catálogo: cambios completos, sin truncar
# ---------------------------------------------------------------------------


def test_detalle_agencia_sin_truncar_ni_enmascarar(http, monkeypatch):
    """Cambio de dirección de agencia con valor largo: completo y sin enmascarar."""
    _sesion("ADMIN")
    _mock_valor(monkeypatch)

    valor_largo = "A" * 2000
    fila = _evento_fila(
        TipoObjetivo="Organizacion.Agencia",
        Cambios=f'{{"antes":{{"direccion":"{valor_largo}"}},'
        f'"despues":{{"direccion":"Av. Nueva"}}}}',
    )
    monkeypatch.setattr(repository, "obtener_evento", lambda c, i: fila)
    monkeypatch.setattr(repository, "obtener_aprobacion", lambda c, i: None)
    monkeypatch.setattr(repository, "obtener_relacionados", lambda *a: [])

    r = http.get(f"{BASE}/eventos/100")
    assert r.status_code == 200
    body = r.json()
    # No truncado
    assert len(body["cambios"]["antes"]["direccion"]) == 2000
    # No enmascarado (no es Clientes)
    assert body["cambios"]["antes"]["direccion"] == valor_largo


# ---------------------------------------------------------------------------
# AC3 · CAJERO → 403 y se audita el rechazo
# ---------------------------------------------------------------------------


def test_cajero_403_en_busqueda(http, monkeypatch, eventos_auditados):
    """Un CAJERO no puede consultar la bitácora."""
    _sesion("CAJERO")
    _mock_valor(monkeypatch)

    r = http.post(
        f"{BASE}/eventos/busqueda",
        json={
            "desde": "2026-11-01",
            "hasta": "2026-11-20",
        },
    )
    assert r.status_code == 403
    # AccesoDenegadoMiddleware registra ACCESO_DENEGADO
    accesos = [e for e in eventos_auditados if e.accion == "ACCESO_DENEGADO"]
    assert len(accesos) >= 1


# ---------------------------------------------------------------------------
# AC4 · Búsqueda exitosa → AUD_LECTURA registrado
# ---------------------------------------------------------------------------


def test_busqueda_exitosa_audita_lectura(http, monkeypatch, eventos_auditados):
    """Una búsqueda exitosa registra AUD_LECTURA."""
    _sesion("ADMIN")
    _mock_valor(monkeypatch)
    monkeypatch.setattr(repository, "buscar_eventos", lambda *a: ([], 0))

    r = http.post(
        f"{BASE}/eventos/busqueda",
        json={
            "desde": "2026-11-01",
            "hasta": "2026-11-20",
        },
    )
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    lecturas = [e for e in eventos_auditados if e.accion == "AUD_LECTURA"]
    assert len(lecturas) == 1
    assert lecturas[0].tabla == "Auditoria.Auditoria"
    assert "busqueda" in lecturas[0].descripcion


# ---------------------------------------------------------------------------
# AC5 · Rango obligatorio y límite de días
# ---------------------------------------------------------------------------


def test_sin_rango_400(http, monkeypatch):
    """Sin desde/hasta → 400 RANGO_REQUERIDO."""
    _sesion("ADMIN")
    _mock_valor(monkeypatch)

    r = http.post(f"{BASE}/eventos/busqueda", json={})
    assert r.status_code == 400
    assert r.json()["code"] == "RANGO_REQUERIDO"


def test_rango_excedido_422(http, monkeypatch):
    """Rango de más de N días → 422 RANGO_EXCEDIDO."""
    _sesion("ADMIN")
    _mock_valor(monkeypatch, dias=5)

    r = http.post(
        f"{BASE}/eventos/busqueda",
        json={
            "desde": "2026-11-01",
            "hasta": "2026-11-30",
        },
    )
    assert r.status_code == 422
    assert r.json()["code"] == "RANGO_EXCEDIDO"


# ---------------------------------------------------------------------------
# AC6 · Detalle lista eventos relacionados por correlación
# ---------------------------------------------------------------------------


def test_detalle_lista_relacionados(http, monkeypatch):
    """El detalle devuelve eventos con la misma correlación."""
    _sesion("ADMIN")
    _mock_valor(monkeypatch)

    fila_principal = _evento_fila(IdCorrelacion="corr-abc")
    fila_rel = _evento_fila(AuditoriaID=101, IdCorrelacion="corr-abc")

    monkeypatch.setattr(repository, "obtener_evento", lambda c, i: fila_principal)
    monkeypatch.setattr(repository, "obtener_aprobacion", lambda c, i: None)
    monkeypatch.setattr(repository, "obtener_relacionados", lambda *a: [fila_rel])

    r = http.get(f"{BASE}/eventos/100")
    assert r.status_code == 200
    body = r.json()
    assert len(body["relacionados"]) == 1
    assert body["relacionados"][0]["id"] == 101


# ---------------------------------------------------------------------------
# AC extra · SUPERVISOR sin acceso a agencia → 403
# ---------------------------------------------------------------------------


def test_supervisor_agencia_no_autorizada(http, monkeypatch):
    """SUPERVISOR con filtro de agencia fuera de su alcance → 403."""
    _sesion("SUPERVISOR", agencia="001", agencias=("001",))
    _mock_valor(monkeypatch)

    r = http.post(
        f"{BASE}/eventos/busqueda",
        json={
            "desde": "2026-11-01",
            "hasta": "2026-11-20",
            "agencia": "999",
        },
    )
    assert r.status_code == 403
    assert r.json()["code"] == "AGENCIA_NO_AUTORIZADA"


# ---------------------------------------------------------------------------
# AC extra · Exportación > 1000 filas → 422
# ---------------------------------------------------------------------------


def test_exportacion_demasiadas_filas(http, monkeypatch):
    """Más de 1000 filas → 422 EXPORTACION_MUY_GRANDE."""
    _sesion("ADMIN", exportar=True)
    _mock_valor(monkeypatch)
    monkeypatch.setattr(repository, "buscar_eventos", lambda *a: ([], 1001))

    r = http.post(
        f"{BASE}/eventos/exportacion",
        json={
            "desde": "2026-11-01",
            "hasta": "2026-11-20",
            "formato": "csv",
        },
    )
    assert r.status_code == 422
    assert r.json()["code"] == "EXPORTACION_MUY_GRANDE"


def test_exportacion_pdf_se_registra_antes_de_entregar(http, monkeypatch):
    """PDF adjunto, sin caché y con AUD_EXPORTACION registrado en su transacción."""
    _sesion("AUDITOR", exportar=True)
    _mock_valor(monkeypatch)
    registrados: list[audit.EventoAuditoria] = []
    monkeypatch.setattr(repository, "buscar_eventos", lambda *a: ([_evento_fila()], 1))
    monkeypatch.setattr(
        "app.modules.auditoria.router.pdf_tool.institucion_actual",
        lambda conn: "Cooperativa de prueba",
    )
    monkeypatch.setattr(
        "app.modules.auditoria.router.get_engine", lambda _: MagicMock()
    )
    monkeypatch.setattr(
        audit, "registrar_en_transaccion", lambda c, e: registrados.append(e)
    )

    r = http.post(
        f"{BASE}/eventos/exportacion",
        json={"desde": "2026-11-01", "hasta": "2026-11-20", "formato": "pdf"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "no-store" in r.headers["cache-control"]
    assert [e.accion for e in registrados] == ["AUD_EXPORTACION"]


def test_supervisor_no_ve_evento_de_otra_agencia(http, monkeypatch):
    """Fuera del alcance de agencia el evento no existe para el lector (404)."""
    _sesion("SUPERVISOR", agencias=("001",))
    monkeypatch.setattr(
        repository, "obtener_evento", lambda c, i: _evento_fila(IdAgencia="002")
    )
    r = http.get(f"{BASE}/eventos/100")
    assert r.status_code == 404
    assert r.json()["code"] == "EVENTO_NO_ENCONTRADO"

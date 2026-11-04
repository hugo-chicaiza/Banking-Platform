import logging

from fastapi.testclient import TestClient

from app.core.config.logs import _AgregarTraceId, _Formato, trace_id_actual
from app.core.database.db import cooperativa
from app.main import app
from app.modules.catalogos import repository


def _registro(mensaje: str) -> logging.LogRecord:
    return logging.LogRecord(
        "app.prueba", logging.INFO, __file__, 1, mensaje, None, None
    )


def test_formato_lleva_hora_nivel_modulo_y_trace_id():
    token = trace_id_actual.set("abc-123")
    try:
        registro = _registro("hola")
        _AgregarTraceId().filter(registro)
    finally:
        trace_id_actual.reset(token)

    linea = _Formato().format(registro)

    assert linea.endswith(" INFO app.prueba trace=abc-123 hola")
    assert linea[:4].isdigit()


def test_salto_de_linea_no_crea_entradas_falsas():
    registro = _registro("GET /api/v1/x\n2026-01-01 ERROR falso")
    _AgregarTraceId().filter(registro)

    linea = _Formato().format(registro)

    assert "\n" not in linea
    assert "\\n2026-01-01 ERROR falso" in linea


def test_fuera_de_una_peticion_trace_id_es_guion():
    registro = _registro("arranque")
    _AgregarTraceId().filter(registro)

    assert registro.__dict__["trace_id"] == "-"


def test_clientes_http_no_escriben_urls_en_info():
    for nombre in ("httpx", "httpcore", "uvicorn.access"):
        assert not logging.getLogger(nombre).isEnabledFor(logging.INFO)


def test_cada_peticion_deja_una_linea_sin_query_string(caplog):
    caplog.set_level(logging.INFO, logger="app.peticiones")

    respuesta = TestClient(app).get(
        "/ruta-que-no-existe?identificacion=1712345678",
        headers={"X-Request-Id": "prueba-log-1"},
    )

    registros = [r for r in caplog.records if r.name == "app.peticiones"]
    assert len(registros) == 1
    mensaje = registros[0].getMessage()
    assert mensaje.startswith("GET /ruta-que-no-existe status=404 ms=")
    assert "1712345678" not in mensaje
    assert respuesta.headers["X-Request-Id"] == "prueba-log-1"


def test_logs_de_un_modulo_llevan_el_trace_id_de_su_peticion(monkeypatch):
    """Cualquier módulo, no solo el middleware, ve el traceId de su petición."""
    vistos: list[str] = []

    def listar_paises(conn):
        vistos.append(trace_id_actual.get())
        return []

    monkeypatch.setattr(repository, "listar_paises", listar_paises)
    app.dependency_overrides[cooperativa] = lambda: None
    try:
        TestClient(app).get(
            "/api/v1/catalogos/paises", headers={"X-Request-Id": "trace-cat-1"}
        )
    finally:
        app.dependency_overrides.clear()

    assert vistos == ["trace-cat-1"]

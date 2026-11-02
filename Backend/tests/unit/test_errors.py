"""Formato de errores de F-04, traceId y traducción de errores de BD."""

import logging

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.core.db import cooperativa
from app.core.errors import ProblemDetailsRoute
from app.core.middleware import TraceIdMiddleware
from app.main import app as app_real
from app.modules.catalogos import repository as repo_catalogos


class _Cuerpo(BaseModel):
    nombre: str
    edad: int


def _error_bd(mensaje: str) -> DBAPIError:
    return DBAPIError("SELECT secreto", {"p": "PARAMETRO_SECRETO"}, Exception(mensaje))


router = APIRouter(route_class=ProblemDetailsRoute)


@router.get("/http/{estado}")
def http(estado: int) -> None:
    raise HTTPException(estado, detail={"code": f"C_{estado}", "message": "Mensaje"})


@router.get("/texto")
def texto() -> None:
    raise HTTPException(404, detail="No existe")


@router.get("/bd/{numero}")
def bd(numero: int) -> None:
    raise _error_bd(f"[SQL Server]Mensaje interno ({numero}) (SQLExecDirectW)")


@router.get("/bd-caida")
def bd_caida() -> None:
    raise _error_bd("Conexión rechazada al servidor interno")


@router.get("/sqlalchemy")
def sqlalchemy_generico() -> None:
    raise SQLAlchemyError("detalle interno SECRETO")


@router.get("/inesperado")
def inesperado() -> None:
    raise RuntimeError("detalle interno SECRETO")


@router.post("/cuerpo")
def cuerpo(_datos: _Cuerpo) -> None:
    return None


@router.get("/ok")
def correcto() -> dict[str, str]:
    return {"ok": "si"}


_app = FastAPI()
_app.add_middleware(TraceIdMiddleware)
_app.include_router(router)
client = TestClient(_app)


def _es_problema(r, status: int, code: str) -> dict:
    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/problem+json")
    cuerpo = r.json()
    assert cuerpo["type"] == "about:blank"
    assert cuerpo["status"] == status
    assert cuerpo["code"] == code
    assert cuerpo["title"] and cuerpo["detail"]
    assert cuerpo["traceId"] == r.headers["x-request-id"]
    assert r.headers["cache-control"] == "no-store"
    return cuerpo


@pytest.mark.parametrize("estado", [400, 401, 403, 404, 409, 422, 423])
def test_cada_estado_sale_como_problem_details(estado):
    _es_problema(client.get(f"/http/{estado}"), estado, f"C_{estado}")


def test_detalle_de_texto_recibe_codigo_generico():
    cuerpo = _es_problema(client.get("/texto"), 404, "HTTP_404")

    assert cuerpo["detail"] == "No existe"
    assert cuerpo["title"] == "Not Found"


def test_validacion_es_400_con_campos_y_sin_el_valor_recibido():
    r = client.post("/cuerpo", json={"nombre": 1234, "edad": "VALOR_SECRETO"})

    cuerpo = _es_problema(r, 400, "DATOS_INVALIDOS")
    assert {e["field"] for e in cuerpo["errors"]} == {"nombre", "edad"}
    assert "VALOR_SECRETO" not in r.text
    assert "1234" not in r.text
    assert "input" not in r.text


def test_json_mal_formado_es_400():
    r = client.post(
        "/cuerpo", content=b"{no json", headers={"content-type": "application/json"}
    )

    cuerpo = _es_problema(r, 400, "DATOS_INVALIDOS")
    assert cuerpo["errors"] == [{"field": "body", "message": "JSON mal formado"}]


@pytest.mark.parametrize(
    ("numero", "status", "code"),
    [
        (52001, 409, "CLIENTE_NO_ACTIVO"),
        (52002, 409, "CUENTA_NO_ACTIVA"),
        (52003, 422, "CUPO_EXCEDE_PRODUCTO"),
        (52004, 422, "BIN_INVALIDO"),
        (52005, 409, "TRANSICION_TARJETA_INVALIDA"),
        (57001, 409, "REGISTRO_INMUTABLE"),
        (59999, 422, "DB_59999"),
    ],
)
def test_throw_de_bd_se_traduce_sin_exponer_sql(numero, status, code):
    r = client.get(f"/bd/{numero}")

    _es_problema(r, status, code)
    for filtrado in ("SELECT", "SECRETO", "SQL Server", "Mensaje interno"):
        assert filtrado not in r.text


@pytest.mark.parametrize("ruta", ["/bd-caida", "/sqlalchemy", "/inesperado"])
def test_error_500_es_generico_y_el_log_no_tiene_detalles(ruta, caplog):
    caplog.set_level(logging.DEBUG)

    r = client.get(ruta)

    _es_problema(r, 500, "ERROR_INTERNO")
    for texto_filtrado in (r.text, caplog.text):
        assert "SECRETO" not in texto_filtrado
        assert "interno al" not in texto_filtrado
    assert caplog.records


def test_trace_id_valido_del_cliente_se_conserva():
    r = client.get("/http/404", headers={"X-Request-Id": "req-123"})

    assert r.json()["traceId"] == "req-123"
    assert r.headers["x-request-id"] == "req-123"


@pytest.mark.parametrize("valor", ["con espacios", "a" * 65, "x<script>"])
def test_trace_id_inseguro_se_reemplaza(valor):
    r = client.get("/http/404", headers={"X-Request-Id": valor})

    assert r.json()["traceId"] != valor
    assert r.headers["x-request-id"] == r.json()["traceId"]


def test_respuesta_correcta_lleva_el_trace_id_y_no_cambia():
    r = client.get("/ok", headers={"X-Request-Id": "req-9"})

    assert r.status_code == 200
    assert r.json() == {"ok": "si"}
    assert r.headers["x-request-id"] == "req-9"


# Aplicación real


@pytest.fixture
def real():
    app_real.dependency_overrides[cooperativa] = lambda: None
    yield TestClient(app_real)
    app_real.dependency_overrides.clear()


def test_cat02_pais_inexistente_404(real, monkeypatch):
    monkeypatch.setattr(repo_catalogos, "existe_pais", lambda _c, _p: False)

    r = real.get("/api/v1/catalogos/paises/XXX/ciudades")

    _es_problema(r, 404, "PAIS_NO_ENCONTRADO")


def test_cat02_codigo_invalido_400(real):
    r = real.get("/api/v1/catalogos/paises/EC/ciudades")

    cuerpo = _es_problema(r, 400, "DATOS_INVALIDOS")
    assert cuerpo["errors"][0]["field"] == "codigo_pais"


def test_catalogo_con_bd_caida_500_generico(real, monkeypatch):
    def falla(_c):
        raise _error_bd("Conexión rechazada")

    monkeypatch.setattr(repo_catalogos, "listar_paises", falla)

    r = real.get("/api/v1/catalogos/paises")

    _es_problema(r, 500, "ERROR_INTERNO")


def test_429_usa_problem_details():
    c = TestClient(app_real, client=("8.8.4.4", 5000))
    respuestas = [c.post("/api/v1/tarjetas/1/pin", json={"pin": "x"}) for _ in range(6)]

    _es_problema(respuestas[5], 429, "DEMASIADAS_SOLICITUDES")
    assert respuestas[5].headers["retry-after"]


def test_openapi_documenta_problem_details_en_los_routers_migrados():
    rutas = app_real.openapi()["paths"]

    for ruta in ("/api/v1/catalogos/paises", "/api/v1/tarjetas"):
        respuestas = rutas[ruta]["get"]["responses"]
        assert "application/problem+json" in respuestas["400"]["content"]


def test_modulos_sin_migrar_conservan_su_formato(real, monkeypatch):
    from app.modules.contabilidad import repository

    for nombre in dir(repository):
        if nombre.startswith(("obtener", "buscar")):
            monkeypatch.setattr(repository, nombre, lambda *_a, **_k: None)

    r = real.get("/api/v1/contabilidad/fechas-contables/2026-13-99")

    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/json")
    assert "code" in r.json()["detail"]
    assert r.headers["x-request-id"]

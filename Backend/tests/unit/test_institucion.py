from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.config.settings import Settings
from app.modules.organizacion import service as institucion
from app.modules.organizacion.router import router_publico


def config(**valores):
    # Valores controlados de prueba; no carga .env ni variables reales de la máquina.
    return Settings.model_construct(**valores)


def test_entidad_prioritaria_sin_mezclar_web_de_entorno():
    resultado = institucion.resolver_presentacion(
        {
            "nombre_comercial": "  Cooperativa Ámbito  ",
            "razon_social": "Otra",
            "sitio_web": None,
        },
        config(
            cooperativa_nombre="Inicial",
            cooperativa_sitio_web="https://example.invalid",
        ),
    )
    assert resultado.model_dump(by_alias=True) == {
        "nombre": "Cooperativa Ámbito",
        "sitioWeb": None,
        "logoUrl": None,
        "origen": "ENTIDAD",
    }


def test_razon_social_si_nombre_comercial_vacio():
    resultado = institucion.resolver_presentacion(
        {
            "nombre_comercial": "  ",
            "razon_social": "Razón social",
            "sitio_web": "https://example.invalid",
        },
        config(),
    )
    assert resultado.nombre == "Razón social"
    assert resultado.sitio_web == "https://example.invalid"


def test_entorno_explicito_y_sin_configuracion():
    assert institucion.resolver_presentacion(None, config()).origen == "SIN_CONFIGURAR"
    resultado = institucion.resolver_presentacion(
        None, config(cooperativa_nombre="Instalación QA")
    )
    assert resultado.origen == "ENTORNO" and resultado.nombre == "Instalación QA"


@pytest.mark.parametrize(
    "valor",
    [
        "javascript:alert(1)",
        "http://example.invalid",
        "//example.invalid",
        "https://user:pass@example.invalid",
        "https://example.invalid\nmal",
        "https://example.invalid:abc",
    ],
)
def test_no_publica_enlaces_inseguros(valor):
    assert institucion.sitio_web_seguro(valor) is None


def test_endpoint_publico_solo_expone_contrato_minimo(monkeypatch):
    monkeypatch.setattr(institucion, "get_settings", lambda: config())
    app = FastAPI()
    app.include_router(router_publico, prefix="/api/v1")
    with TestClient(app) as cliente:
        respuesta = cliente.get("/api/v1/institucion")
    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.json() == {
        "nombre": None,
        "sitioWeb": None,
        "logoUrl": None,
        "origen": "SIN_CONFIGURAR",
    }


def test_caida_sql_es_503_y_no_falso_vacio(monkeypatch):
    monkeypatch.setattr(
        institucion,
        "get_settings",
        lambda: config(cooperativa_db_server="local", cooperativa_db_name="QA"),
    )
    motor = MagicMock()
    motor.connect.side_effect = SQLAlchemyError("detalle privado que nunca se publica")
    monkeypatch.setattr(institucion, "get_engine", lambda _: motor)
    app = FastAPI()
    app.include_router(router_publico, prefix="/api/v1")
    with TestClient(app) as cliente:
        respuesta = cliente.get("/api/v1/institucion")
    assert respuesta.status_code == 503
    assert respuesta.json()["code"] == "INSTITUCION_NO_DISPONIBLE"
    assert "privado" not in respuesta.text


def test_lectura_sql_solo_selecciona_los_tres_campos_publicos(monkeypatch):
    from app.modules.organizacion import repository

    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "nombre_comercial": "Nombre QA",
        "razon_social": "Razón QA",
        "sitio_web": None,
    }
    fila = repository.obtener_presentacion_entidad(conn)
    consulta = conn.execute.call_args.args[0]
    assert list(consulta.selected_columns.keys()) == [
        "nombre_comercial",
        "razon_social",
        "sitio_web",
    ]
    assert fila is not None and fila["nombre_comercial"] == "Nombre QA"
    conn.commit.assert_not_called()


def test_entidad_inexistente_usa_entorno_sin_escribir(monkeypatch):
    motor = MagicMock()
    conn = motor.connect.return_value.__enter__.return_value
    monkeypatch.setattr(institucion, "get_engine", lambda _: motor)
    monkeypatch.setattr(
        institucion.repo, "obtener_presentacion_entidad", lambda _: None
    )
    monkeypatch.setattr(
        institucion,
        "get_settings",
        lambda: config(
            cooperativa_db_server="local",
            cooperativa_db_name="QA",
            cooperativa_nombre="Configuración QA",
        ),
    )
    assert institucion.obtener_presentacion().origen == "ENTORNO"
    conn.commit.assert_not_called()


def test_presentacion_no_admite_escrituras(monkeypatch):
    monkeypatch.setattr(institucion, "get_settings", lambda: config())
    app = FastAPI()
    app.include_router(router_publico, prefix="/api/v1")
    with TestClient(app) as cliente:
        for metodo in ("post", "patch", "put", "delete"):
            assert (
                cliente.request(metodo, "/api/v1/institucion", json={}).status_code
                == 405
            )


def test_referencia_generada_cubre_settings_sin_valores_del_entorno(monkeypatch):
    import re

    from scripts.referencia_configuracion import generar

    monkeypatch.setenv("WORKOS_API_KEY", "secreto-ficticio-no-publicar")
    referencia = generar()
    nombres = re.findall(r"^\| `([A-Z][A-Z0-9_]+)` \|", referencia, re.MULTILINE)
    assert set(nombres) == {nombre.upper() for nombre in Settings.model_fields}
    assert len(nombres) == len(Settings.model_fields)
    assert "secreto-ficticio-no-publicar" not in referencia

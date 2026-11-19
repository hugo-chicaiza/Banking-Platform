"""E0-03: contrato por módulo (sin activar en el pipeline). Pruebas con un OpenAPI sintético."""

import copy
import importlib.util
from pathlib import Path

import pytest

_RUTA = Path(__file__).resolve().parents[2] / "scripts" / "contrato.py"
_spec = importlib.util.spec_from_file_location("contrato", _RUTA)
assert _spec and _spec.loader
contrato = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contrato)

OPENAPI = {
    "openapi": "3.1.0",
    "info": {"version": "1.0"},
    "paths": {
        "/api/v1/cuentas": {
            "get": {
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Cuenta"}
                            }
                        }
                    }
                }
            }
        },
        "/api/v1/caja/depositos": {
            "post": {
                "parameters": [],
                "responses": {
                    "201": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Deposito"}
                            }
                        }
                    },
                    "422": {"content": {"application/json": {}}},
                },
            }
        },
        "/api/v1/pruebas/pin-block": {"post": {"responses": {"200": {}}}},
    },
    "components": {
        "schemas": {
            "Cuenta": {
                "properties": {
                    "saldo": {"type": "string"},
                    "titular": {"$ref": "#/components/schemas/Persona"},
                }
            },
            "Persona": {"properties": {"nombre": {"type": "string"}}},
            "Deposito": {"properties": {"monto": {"type": "number"}}},
            "SinUso": {"properties": {}},
        }
    },
}


def test_parte_por_modulo_con_solo_los_esquemas_que_usa():
    modulos = contrato.por_modulo(OPENAPI)
    assert sorted(modulos) == ["caja", "cuentas"]  # el PIN pad de prueba no es contrato
    assert sorted(modulos["cuentas"]["components"]["schemas"]) == [
        "Cuenta",
        "Persona",
    ]  # transitivo
    assert "SinUso" not in modulos["caja"]["components"]["schemas"]


def test_exportar_y_comparar_coinciden(tmp_path):
    contrato.exportar(OPENAPI, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["caja.json", "cuentas.json"]
    assert contrato.comparar(OPENAPI, tmp_path) == []


def test_ruta_nueva_sin_contrato_se_nombra(tmp_path):  # criterio 1
    contrato.exportar(OPENAPI, tmp_path)
    nuevo = copy.deepcopy(OPENAPI)
    nuevo["paths"]["/api/v1/cuentas/{id}"] = {"delete": {"responses": {"204": {}}}}
    assert contrato.comparar(nuevo, tmp_path) == [
        "DELETE /api/v1/cuentas/{id}: está en el código y no en el contrato (cuentas.json)"
    ]


def test_ruta_del_contrato_que_ya_no_existe_se_nombra(tmp_path):
    contrato.exportar(OPENAPI, tmp_path)
    sin_caja = copy.deepcopy(OPENAPI)
    del sin_caja["paths"]["/api/v1/caja/depositos"]
    assert contrato.comparar(sin_caja, tmp_path) == [
        "POST /api/v1/caja/depositos: está en el contrato (caja.json) y no en el código"
    ]


def test_campo_cambiado_se_detecta(tmp_path):
    contrato.exportar(OPENAPI, tmp_path)
    cambiado = copy.deepcopy(OPENAPI)
    cambiado["components"]["schemas"]["Persona"]["properties"]["nombre"]["type"] = (
        "integer"
    )
    diferencias = contrato.comparar(cambiado, tmp_path)
    assert diferencias == [
        "GET /api/v1/cuentas: parámetros, cuerpo, respuestas o esquemas distintos del contrato"
    ]


@pytest.mark.parametrize(
    "esperado",
    [
        "POST /api/v1/caja/depositos: errores sin application/problem+json",
        "POST /api/v1/caja/depositos: operación de dinero sin cabecera Idempotency-Key",
        "Deposito.monto: monto como número; la convención es cadena decimal con 2 posiciones",
    ],
)
def test_convenciones_avisan(esperado):
    assert esperado in contrato.convenciones(OPENAPI)


def test_contrato_confirmado_existe_por_modulo():
    # El contrato de partida está en el repositorio; su comparación en el pipeline es E0-11 (al activarse)
    carpeta = Path(__file__).resolve().parents[2] / "contract"
    assert {"cuentas.json", "caja.json", "auth.json"} <= {
        p.name for p in carpeta.glob("*.json")
    }

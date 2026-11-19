"""E0-13: registros sin datos sensibles, formato JSON y rutas de una construcción de producción."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config.logs import _Formato, _FormatoJson, enmascarar

BACKEND = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("texto", "no_debe", "debe"),
    [
        (
            "tarjeta 4111 1111 1111 1111 rechazada",
            "4111 1111 1111 1111",
            "[PAN ****1111]",
        ),
        ("pan=4111111111111111", "4111111111111111", "[PAN ****1111]"),
        (
            "Authorization: Bearer abc.def.ghijklmnop",
            "abc.def.ghijklmnop",
            "Bearer [token]",
        ),
        (
            "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N",
            "eyJhbGci",
            "[token]",
        ),
        (
            "clave WORKOS sk_test_a1b2c3d4e5f6g7h8",
            "sk_test_a1b2c3d4e5f6g7h8",
            "[secreto]",
        ),
        ("password=Sup3rSecreta! usuario=ana", "Sup3rSecreta!", "password=[oculto]"),
        ("pin: 1234 confirmado", "1234", "pin: [oculto]"),
    ],
)
def test_enmascara_datos_sensibles(texto, no_debe, debe):
    limpio = enmascarar(texto)
    assert no_debe not in limpio and debe in limpio


@pytest.mark.parametrize(
    "texto", ["cuenta 2100004563 saldo", "solicitud 1234567890123", "agencia=001 ms=12"]
)
def test_no_toca_numeros_que_no_son_tarjetas(texto):
    # Una cuenta de 10 dígitos o un número que no pasa Luhn no es un PAN
    assert enmascarar(texto) == texto


def _registro(mensaje: str, *args) -> logging.LogRecord:
    registro = logging.LogRecord(
        "app.prueba", logging.INFO, __file__, 1, mensaje, args, None
    )
    registro.trace_id = "abc123"
    return registro


def test_formato_texto_enmascara_y_no_parte_la_linea():
    linea = _Formato().format(
        _registro("ruta %s tarjeta %s", "/x\nFALSO INFO", "4111111111111111")
    )
    assert "\n" not in linea and "trace=abc123" in linea
    assert "4111111111111111" not in linea and "[PAN ****1111]" in linea


def test_formato_json_una_linea_por_registro():
    linea = _FormatoJson().format(_registro("token=%s", "abcdef123456"))
    datos = json.loads(linea)
    assert datos["traceId"] == "abc123" and datos["nivel"] == "INFO"
    assert datos["mensaje"] == "token=[oculto]"
    assert "\n" not in linea


def _rutas(entorno: str) -> dict:
    """Arranca la app en otro proceso con APP_ENV=entorno: rutas, documentación y la
    respuesta de la ruta de prueba del PIN pad."""
    codigo = (
        "import json, sys; sys.path.insert(0, '.')\n"
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "r = TestClient(app).post('/api/v1/pruebas/pin-block', json={})\n"
        "print(json.dumps({'rutas': [getattr(x, 'path', '') for x in app.routes],"
        " 'pin_pad': r.status_code}))"
    )
    env = {**os.environ, "APP_ENV": entorno}
    salida = subprocess.run(
        [sys.executable, "-I", "-c", codigo],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(salida.stdout.strip().splitlines()[-1])


def test_produccion_sin_documentacion_y_sin_la_ruta_de_prueba_del_pin_pad():
    prod = _rutas("production")
    assert not [r for r in prod["rutas"] if "docs" in r or "openapi" in r]
    assert prod["pin_pad"] == 404  # la ruta de prueba no responde en producción
    # En desarrollo sí existe la documentación: la prueba distingue los dos casos
    assert "/api/docs" in _rutas("development")["rutas"]

import pytest
from fastapi import HTTPException

from app.modules.contabilidad.importaciones import leer_csv, revisar

CABECERA = b"CodigoCuenta,NombreCuenta,CodigoCuentaSuperior,Naturaleza\n"


def test_previsualiza_padres_y_reporta_fila():
    filas = leer_csv(
        "cuc.csv",
        CABECERA + b"11,Fondos,1,DEUDORA\n1,Activo,,DEUDORA\n12,Error,2,DEUDORA\n",
    )
    revision = revisar(filas, {})
    assert [(f["numeroFila"], f["resultado"]) for f in revision] == [
        (2, "Nueva"),
        (3, "Nueva"),
        (4, "Error"),
    ]
    assert revision[2]["codigoError"] == "CODIGO_NO_CORRESPONDE_AL_PADRE"


def test_rechaza_cambio_de_naturaleza_con_lineas():
    filas = leer_csv("cuc.csv", CABECERA + b"1,Activo,,ACREEDORA\n")
    plan = {"1": {"naturaleza": "DEUDORA", "movimientos": True}}
    assert revisar(filas, plan)[0]["codigoError"] == "NATURALEZA_EN_USO"


def test_revision_distingue_cambios_y_rechaza_auxiliares():
    filas = leer_csv(
        "cuc.csv",
        CABECERA
        + b"1,Activo,,DEUDORA\n11,Fondos,1,DEUDORA\n1101,Nueva,11,DEUDORA\n"
        + b"11010101,Auxiliar,110101,DEUDORA\n",
    )
    cuenta = {
        "naturaleza": "DEUDORA",
        "regulador": True,
        "imputable": False,
    }
    plan = {
        "1": {**cuenta, "nombre": "Activo", "padre": None},
        "11": {**cuenta, "nombre": "Anterior", "padre": "1"},
        "11010101": {**cuenta, "nombre": "Auxiliar", "padre": "110101"},
    }
    revision = revisar(filas, plan)
    assert [fila["resultado"] for fila in revision] == [
        "Igual",
        "Cambiada",
        "Nueva",
        "Error",
    ]
    assert revision[-1]["codigoError"] == "CODIGO_INVALIDO"


@pytest.mark.parametrize(
    "nombre,contenido",
    [
        ("cuc.exe", CABECERA),
        ("cuc.csv", b"mal\xff"),
        ("cuc.csv", CABECERA + b"a,b,c\n"),
        ("cuc.csv", b"Naturaleza,CodigoCuenta,NombreCuenta,CodigoCuentaSuperior\n"),
        ("cuc.csv", CABECERA),
    ],
)
def test_archivo_invalido(nombre, contenido):
    with pytest.raises(HTTPException) as error:
        leer_csv(nombre, contenido)
    assert error.value.status_code == 422
    assert isinstance(error.value.detail, dict)
    assert error.value.detail.get("code") == "ARCHIVO_INVALIDO"


def test_carga_csv_fragmentada_conserva_utf8_y_no_escribe_directamente(monkeypatch):
    import asyncio
    from unittest.mock import Mock

    from fastapi import Request

    from app.modules.contabilidad import importaciones

    contenido = CABECERA + "1,Ahorro Ni\u00f1ez,,DEUDORA\n".encode()
    posicion = contenido.index(bytes([0xC3])) + 1
    fragmentos = iter([contenido[:posicion], contenido[posicion:]])

    async def recibir():
        fragmento = next(fragmentos, b"")
        return {"type": "http.request", "body": fragmento, "more_body": bool(fragmento)}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"content-type", b"text/csv")],
        },
        recibir,
    )
    guardar = Mock(return_value={"IdImportacion": 7})
    monkeypatch.setattr(importaciones, "guardar_revision", guardar)
    conn = Mock()
    respuesta = asyncio.run(importaciones.subir(conn, 101, request, "cuc.csv"))
    assert respuesta == {"IdImportacion": 7}
    guardar.assert_called_once_with(
        conn, 101, "cuc.csv", leer_csv("cuc.csv", contenido)
    )
    assert guardar.call_args.args[3][0]["Naturaleza"] == "DEUDORA"
    conn.execute.assert_not_called()


def test_carga_csv_rechaza_limite_antes_de_guardar(monkeypatch):
    import asyncio
    from unittest.mock import Mock

    from fastapi import Request

    from app.modules.contabilidad import importaciones

    monkeypatch.setattr(importaciones, "MAX_BYTES", 3)

    async def recibir():
        return {"type": "http.request", "body": b"1234", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"content-type", b"text/csv")],
        },
        recibir,
    )
    guardar = Mock()
    monkeypatch.setattr(importaciones, "guardar_revision", guardar)
    with pytest.raises(HTTPException) as error:
        asyncio.run(importaciones.subir(Mock(), 101, request, "cuc.csv"))
    assert error.value.status_code == 422
    guardar.assert_not_called()


def test_limite_configurable_preserva_tope_y_compatibilidad(monkeypatch):
    from unittest.mock import Mock

    from app.modules.contabilidad import importaciones

    conn = Mock()
    conn.execute.return_value.scalar.return_value = None
    assert importaciones._limite_filas(conn) == 5000
    conn.execute.return_value.scalar.return_value = 1
    monkeypatch.setattr(importaciones.general, "valor", lambda *args: 10)
    assert importaciones._limite_filas(conn) == 10
    monkeypatch.setattr(importaciones.general, "valor", lambda *args: 6000)
    assert importaciones._limite_filas(conn) == 5000


@pytest.mark.parametrize(
    "contenido",
    [
        CABECERA + b"1,Activo\x00,,DEUDORA\n",  # NUL
        CABECERA + b"1,Activo\x1b[2J,,DEUDORA\n",  # control
        CABECERA + b"1,Activo,,DEUDORA\n#!/bin/sh\n",  # script
    ],
)
def test_analisis_rechaza_antes_de_parsear(contenido):
    with pytest.raises(HTTPException) as error:
        leer_csv("cuc.csv", contenido)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "ARCHIVO_INVALIDO"  # type: ignore[index]


def test_eicar_se_rechaza_antes_de_parsear():
    from app.core.documentos.analisis import EICAR

    with pytest.raises(HTTPException) as error:
        leer_csv("cuc.csv", CABECERA + b"1," + EICAR + b",,DEUDORA\n")
    assert error.value.status_code == 422


def test_celdas_de_formula_quedan_como_texto_literal():
    """ASVS 1.2.x/1.2.10: `=CMD|...` no se evalúa; el código no pasa la regla numérica
    y el nombre se conserva literal (va por parámetro SQL y core/csv lo neutraliza)."""
    formula = "=CMD|' /C calc'!A0"
    filas = leer_csv(
        "cuc.csv",
        CABECERA + f'"{formula}",Activo,,DEUDORA\n1,"{formula}",,DEUDORA\n'.encode(),
    )
    assert filas[0]["CodigoCuenta"] == formula and filas[1]["NombreCuenta"] == formula
    revision = revisar(filas, {})
    assert revision[0]["codigoError"] == "CODIGO_INVALIDO"
    assert revision[1]["resultado"] == "Nueva"
    assert revision[1]["NombreCuenta"] == formula

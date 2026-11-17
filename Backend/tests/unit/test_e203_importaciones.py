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


@pytest.mark.parametrize(
    "nombre,contenido",
    [
        ("cuc.exe", CABECERA),
        ("cuc.csv", b"mal\xff"),
        ("cuc.csv", CABECERA + b"a,b,c\n"),
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

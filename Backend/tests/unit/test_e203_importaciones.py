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
    assert error.value.detail["code"] == "ARCHIVO_INVALIDO"

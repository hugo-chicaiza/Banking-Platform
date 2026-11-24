import csv
from contextlib import nullcontext
from dataclasses import replace
from io import StringIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.organizacion import exportacion
from tests.sesion import usuario_con_roles


def test_exportar_requiere_permiso_explicito_aun_para_admin():
    with pytest.raises(HTTPException) as error:
        exportacion.autorizar(usuario_con_roles("ADMIN"))
    assert error.value.status_code == 403


@pytest.mark.parametrize("documento", [None, "", "  ", "1", "1234"])
def test_documento_corto_se_enmascara_por_completo(documento):
    assert exportacion.enmascarar_documento(documento) == "*" * len(
        (documento or "").strip()
    )


@pytest.mark.parametrize(
    "valor", ["\tDato", "\nDato", "\rDato", "\ufeff+123", " -123", "@dato"]
)
def test_csv_neutraliza_prefijos_de_formula(valor):
    assert exportacion.celda_csv(valor) == "'" + valor


def test_csv_conserva_numeros_como_numeros():
    assert exportacion.celda_csv(123) == 123


def test_csv_neutraliza_enmascara_y_audita_antes_de_entregar(monkeypatch):
    eventos = []
    monkeypatch.setattr(
        exportacion,
        "get_engine",
        lambda _: SimpleNamespace(begin=lambda: nullcontext()),
    )
    monkeypatch.setattr(
        exportacion,
        "registrar_en_transaccion",
        lambda _, evento: eventos.append(evento),
    )
    auditor = replace(usuario_con_roles("AUDITOR"), permisos=("org-exportar",))
    documento = "1710034065"
    respuesta = exportacion.responder_csv(
        auditor,
        "127.0.0.1",
        "usuarios",
        "Organizacion.Usuarios",
        ("Nombre", "Documento"),
        [
            ("  =1+1", exportacion.enmascarar_documento(documento)),
            ("Ana Muñoz", "0000"),
        ],
    )

    contenido = bytes(respuesta.body).decode("utf-8")
    assert list(csv.reader(StringIO(contenido))) == [
        ["Nombre", "Documento"],
        ["'  =1+1", "******4065"],
        ["Ana Muñoz", "0000"],
    ]
    assert documento not in contenido
    assert respuesta.headers["content-type"] == "text/csv; charset=utf-8"
    assert eventos[0].accion == "ORG_EXPORTACION"
    assert eventos[0].usuario == auditor.interno()
    assert eventos[0].descripcion == "listado=usuarios filas=2"

"""Exportación CSV común (app.core.csv): ASVS 1.2.10, 14.2.4 y 16.2.5."""

import csv
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.core import csv as exportacion
from app.core.csv import exportacion as modulo
from app.core.security.audit import EventoAuditoria
from tests.sesion import usuario_con_roles


@pytest.fixture
def eventos(monkeypatch) -> list[EventoAuditoria]:
    registrados: list[EventoAuditoria] = []
    monkeypatch.setattr(
        modulo, "get_engine", lambda _: SimpleNamespace(begin=lambda: nullcontext())
    )
    monkeypatch.setattr(
        modulo, "registrar_en_transaccion", lambda _, e: registrados.append(e)
    )
    return registrados


def _auditor() -> Any:
    return replace(usuario_con_roles("AUDITOR"), permisos=("org-exportar",))


def _filas(respuesta: Any) -> list[list[str]]:
    return list(csv.reader(StringIO(bytes(respuesta.body).decode("utf-8"))))


def test_exportar_requiere_permiso_explicito_aun_para_admin():
    with pytest.raises(HTTPException) as error:
        exportacion.autorizar(usuario_con_roles("ADMIN"))
    assert error.value.status_code == 403


def test_sin_permiso_no_audita_ni_entrega(eventos):
    with pytest.raises(HTTPException) as error:
        exportacion.responder_csv(
            usuario_con_roles("ADMIN"), "127.0.0.1", "x", "T", ("a",), [("1",)]
        )
    assert error.value.status_code == 403 and eventos == []


@pytest.mark.parametrize("documento", [None, "", "  ", "1", "1234"])
def test_documento_corto_se_enmascara_por_completo(documento):
    assert exportacion.enmascarar_documento(documento) == "*" * len(
        (documento or "").strip()
    )


@pytest.mark.parametrize(
    "valor",
    [
        "=1+1",
        "+123",
        "-123",
        "@SUM(A1)",
        "=CMD|' /C calc'!A0",
        "\tDato",
        "\nDato",
        "\rDato",
        "﻿+123",
        "﻿=1",
        " -123",
        "  =1+1",
        "@dato",
    ],
)
def test_csv_neutraliza_prefijos_de_formula(valor):
    assert exportacion.celda_csv(valor) == "'" + valor


@pytest.mark.parametrize("valor", ["Ana", "1-2", "correo@dominio", "", "﻿Ana"])
def test_csv_no_toca_texto_normal(valor):
    assert exportacion.celda_csv(valor) == valor


@pytest.mark.parametrize(
    "valor", [123, -5, Decimal("-1.50"), None, True, date(2026, 1, 1)]
)
def test_csv_conserva_celdas_que_no_son_texto(valor):
    assert exportacion.celda_csv(valor) is valor


def test_csv_neutraliza_enmascara_y_audita_antes_de_entregar(eventos):
    auditor = _auditor()
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
    assert _filas(respuesta) == [
        ["Nombre", "Documento"],
        ["'  =1+1", "******4065"],
        ["Ana Muñoz", "0000"],
    ]
    assert documento not in contenido
    assert respuesta.headers["content-type"] == "text/csv; charset=utf-8"
    assert respuesta.headers["cache-control"] == "no-store"
    assert (
        respuesta.headers["content-disposition"]
        == 'attachment; filename="usuarios.csv"'
    )
    assert eventos[0].accion == "ORG_EXPORTACION"
    assert eventos[0].usuario == auditor.interno()
    assert eventos[0].descripcion == "listado=usuarios filas=2"


def test_auditoria_fallida_no_entrega_el_csv(monkeypatch):
    def cae(*_a: Any) -> None:
        raise RuntimeError("auditoría caída")

    monkeypatch.setattr(
        modulo, "get_engine", lambda _: SimpleNamespace(begin=lambda: nullcontext())
    )
    monkeypatch.setattr(modulo, "registrar_en_transaccion", cae)
    with pytest.raises(RuntimeError):
        exportacion.responder_csv(_auditor(), "ip", "x", "T", ("a",), [("1",)])


def test_evento_de_auditoria_parametrizado(eventos):
    exportacion.responder_csv(
        _auditor(),
        "127.0.0.1",
        "clientes",
        "Clientes.Cliente",
        ("id",),
        [(1,)],
        evento="CLI_EXPORTACION",
    )
    assert [e.accion for e in eventos] == ["CLI_EXPORTACION"]
    assert exportacion.EVENTO_EXPORTACION == "ORG_EXPORTACION"


def test_tope_de_filas(eventos):
    filas = [(n,) for n in range(3)]
    respuesta = exportacion.responder_csv(
        _auditor(), "ip", "x", "T", ("n",), filas, max_filas=3
    )
    assert len(_filas(respuesta)) == 4
    with pytest.raises(HTTPException) as error:
        exportacion.responder_csv(
            _auditor(), "ip", "x", "T", ("n",), filas + [(3,)], max_filas=3
        )
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "EXPORTACION_MUY_GRANDE"  # type: ignore[index]
    assert len(eventos) == 1  # el rechazado no se audita como exportado

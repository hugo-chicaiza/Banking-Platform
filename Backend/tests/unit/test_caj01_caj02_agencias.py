"""Pruebas de aislamiento por agencia para CAJ-01 y CAJ-02."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.modules.caja import repository, service
from tests.sesion import usuario_con_roles


def usuario_agencia(*roles, agencia="001"):
    return replace(
        usuario_con_roles(*roles),
        id_agencia=agencia,
    )


@pytest.mark.parametrize("rol", ["CAJERO", "SUPERVISOR"])
def test_caj01_restringe_agencia_propia(monkeypatch, rol):
    recibidos = {}

    def consulta_falsa(conn, id_agencia, activa):
        recibidos["id_agencia"] = id_agencia
        return []

    monkeypatch.setattr(
        repository,
        "listar_cajas_fisicas",
        consulta_falsa,
    )

    service.listar_cajas_fisicas(
        Mock(),
        id_agencia=None,
        activa=None,
        usuario=usuario_agencia(rol),
    )

    assert recibidos["id_agencia"] == "001"


@pytest.mark.parametrize("rol", ["CAJERO", "SUPERVISOR"])
def test_caj01_bloquea_otra_agencia(monkeypatch, rol):
    consulta = Mock(return_value=[])

    monkeypatch.setattr(
        repository,
        "listar_cajas_fisicas",
        consulta,
    )

    with pytest.raises(HTTPException) as error:
        service.listar_cajas_fisicas(
            Mock(),
            id_agencia="002",
            activa=None,
            usuario=usuario_agencia(rol),
        )

    assert error.value.status_code == 403
    consulta.assert_not_called()


def test_caj01_admin_consulta_todas_agencias(monkeypatch):
    recibidos = {}

    def consulta_falsa(conn, id_agencia, activa):
        recibidos["id_agencia"] = id_agencia
        return []

    monkeypatch.setattr(
        repository,
        "listar_cajas_fisicas",
        consulta_falsa,
    )

    service.listar_cajas_fisicas(
        Mock(),
        id_agencia=None,
        activa=None,
        usuario=usuario_con_roles("ADMIN"),
    )

    assert recibidos["id_agencia"] is None


def test_caj02_supervisor_restringe_agencia(monkeypatch):
    recibidos = {}

    def consulta_falsa(conn, **kwargs):
        recibidos.update(kwargs)
        return [], 0

    monkeypatch.setattr(
        repository,
        "listar_jornadas",
        consulta_falsa,
    )

    service.listar_jornadas(
        Mock(),
        usuario=usuario_agencia("SUPERVISOR"),
        id_agencia=None,
        id_usuario=None,
        estado=None,
        desde=None,
        hasta=None,
        page=1,
        page_size=20,
        sort="fechaHoraApertura,desc",
    )

    assert recibidos["id_agencia"] == "001"


def test_caj02_supervisor_bloquea_otra_agencia(monkeypatch):
    consulta = Mock(return_value=([], 0))

    monkeypatch.setattr(
        repository,
        "listar_jornadas",
        consulta,
    )

    with pytest.raises(HTTPException) as error:
        service.listar_jornadas(
            Mock(),
            usuario=usuario_agencia("SUPERVISOR"),
            id_agencia="002",
            id_usuario=None,
            estado=None,
            desde=None,
            hasta=None,
            page=1,
            page_size=20,
            sort="fechaHoraApertura,desc",
        )

    assert error.value.status_code == 403
    consulta.assert_not_called()


@pytest.mark.parametrize("rol", ["CONTADOR", "AUDITOR"])
def test_caj02_roles_globales(monkeypatch, rol):
    recibidos = {}

    def consulta_falsa(conn, **kwargs):
        recibidos.update(kwargs)
        return [], 0

    monkeypatch.setattr(
        repository,
        "listar_jornadas",
        consulta_falsa,
    )

    service.listar_jornadas(
        Mock(),
        usuario=usuario_con_roles(rol),
        id_agencia=None,
        id_usuario=None,
        estado=None,
        desde=None,
        hasta=None,
        page=1,
        page_size=20,
        sort="fechaHoraApertura,desc",
    )

    assert recibidos["id_agencia"] is None

"""Lectura delegada de plantillas, sin ampliar edición ni aprobación implícita."""

from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.main import app
from app.modules.seguridad import funciones
from app.modules.seguridad.funciones_catalogo import POR_ID
from tests.sesion import simular_sesion, usuario_con_roles

CONSULTA = "contabilidad.plantillas.consultar"
EDICION = "contabilidad.plantillas.editar"
LISTADO = "/api/v1/contabilidad/tipos-asiento/1/plantillas"
GLOBAL = "/api/v1/contabilidad/plantillas"
CATALOGOS = f"{GLOBAL}/catalogos"
REGLAS = "/api/v1/contabilidad/reglas-contables"
DETALLE = "/api/v1/contabilidad/plantillas/1"
SIMULACION = "/api/v1/contabilidad/plantillas/simulaciones"


@pytest.fixture
def entorno(monkeypatch):
    ajustes = {}
    monkeypatch.setattr(funciones, "activa", lambda: True)
    monkeypatch.setattr(
        funciones, "efectivos", lambda u: funciones.resolver(ajustes, u)
    )
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "IdPlantillaAsiento": 1,
    }
    app.dependency_overrides[cooperativa] = lambda: conn
    yield ajustes, conn
    app.dependency_overrides.clear()


@pytest.mark.parametrize("rol", ["ADMIN", "SUPERVISOR", "AUDITOR", "CONTADOR"])
def test_cuatro_roles_consultan_sin_permiso_workos_equivalente(entorno, rol):
    simular_sesion(app, replace(usuario_con_roles(rol), permisos=()))
    with TestClient(app) as cliente:
        assert cliente.get(LISTADO).status_code == 200
        assert cliente.get(DETALLE).status_code == 200
        assert cliente.get(GLOBAL).status_code == 200
        assert cliente.get(CATALOGOS).status_code == 200
        assert cliente.get(REGLAS, params={"fecha": "2026-11-25"}).status_code == 200


@pytest.mark.parametrize("rol", ["ADMIN", "SUPERVISOR", "AUDITOR"])
def test_consulta_no_concede_escritura_ni_simulacion(entorno, rol):
    simular_sesion(app, usuario_con_roles(rol))
    with TestClient(app) as cliente:
        assert cliente.post(LISTADO, json={}).status_code == 403
        assert cliente.post(SIMULACION, json={}).status_code == 403


def test_contador_conserva_edicion_y_no_se_salta_validacion(entorno):
    simular_sesion(app, usuario_con_roles("CONTADOR"))
    with TestClient(app) as cliente:
        assert cliente.post(LISTADO, json={}).status_code == 400
        assert cliente.post(SIMULACION, json={}).status_code == 400


def test_retirar_y_restaurar_consulta_bloquea_api_incluso_con_permiso_remoto(entorno):
    ajustes, _ = entorno
    simular_sesion(
        app,
        replace(usuario_con_roles("SUPERVISOR"), permisos=("con-plantilla-editar",)),
    )
    with TestClient(app) as cliente:
        assert cliente.get(LISTADO).status_code == 200
        ajustes[CONSULTA, "SUPERVISOR"] = False
        assert cliente.get(LISTADO).status_code == 403
        assert cliente.get(DETALLE).status_code == 403
        assert cliente.get(GLOBAL).status_code == 403
        assert cliente.get(CATALOGOS).status_code == 403
        assert cliente.get(REGLAS).status_code == 403
        assert cliente.get(f"{DETALLE}/solicitudes").status_code == 403
        ajustes[CONSULTA, "SUPERVISOR"] = True
        assert cliente.get(LISTADO).status_code == 200


def test_delegar_edicion_exige_consulta_y_se_puede_retirar(entorno):
    ajustes, _ = entorno
    simular_sesion(app, usuario_con_roles("SUPERVISOR"))
    ajustes[EDICION, "SUPERVISOR"] = True
    with TestClient(app) as cliente:
        assert cliente.post(SIMULACION, json={}).status_code == 400
        ajustes[EDICION, "SUPERVISOR"] = False
        assert cliente.post(SIMULACION, json={}).status_code == 403
    ajustes[EDICION, "SUPERVISOR"] = True
    ajustes[CONSULTA, "SUPERVISOR"] = False
    with pytest.raises(HTTPException) as error:
        funciones._validar_dependencias(ajustes, {"SUPERVISOR"})
    assert error.value.status_code == 422
    assert (
        EDICION
        not in funciones.resolver(ajustes, usuario_con_roles("SUPERVISOR")).funciones
    )


@pytest.mark.parametrize("rol", ["ASESOR", "CAJERO", "APROBADOR_CREDITO"])
def test_otros_roles_no_reciben_consulta_ni_edicion(entorno, rol):
    simular_sesion(app, usuario_con_roles(rol))
    with TestClient(app) as cliente:
        assert cliente.get(LISTADO).status_code == 403
        assert cliente.get(REGLAS).status_code == 403


def test_control_apagado_conserva_permiso_workos_anterior(entorno, monkeypatch):
    monkeypatch.setattr(funciones, "activa", lambda: False)
    with TestClient(app) as cliente:
        simular_sesion(app, usuario_con_roles("SUPERVISOR"))
        assert cliente.get(LISTADO).status_code == 403
        simular_sesion(app, usuario_con_roles("CONTADOR"))
        assert cliente.get(LISTADO).status_code == 200
        assert cliente.post(SIMULACION, json={}).status_code == 400


def test_catalogo_no_amplia_edicion_o_incluye_aprobacion():
    assert POR_ID[EDICION].roles_iniciales == ("CONTADOR",)
    assert POR_ID[EDICION].dependencias == (CONSULTA,)
    assert len(POR_ID[EDICION].operaciones) == 3
    assert all("aprobacion" not in ruta for _, ruta in POR_ID[EDICION].operaciones)


def test_filtros_validados_y_enviados_a_sql(entorno):
    _, conn = entorno
    simular_sesion(app, usuario_con_roles("CONTADOR"))
    with TestClient(app) as cliente:
        respuesta = cliente.get(
            GLOBAL,
            params={
                "q": "caja",
                "codigo": "DOT_CAJA",
                "estado": 0,
                "origen": "CAJA",
                "idTipoAsiento": 7,
            },
        )
        assert respuesta.status_code == 200
        assert conn.execute.call_args.args[1] == {
            "q": "caja",
            "codigo": "DOT_CAJA",
            "estado": 0,
            "origen": "CAJA",
            "id": 7,
        }
        conn.reset_mock()
        for url in (
            f"{GLOBAL}?estado=2",
            f"{GLOBAL}?idTipoAsiento=0",
            f"{GLOBAL}/{2**31}",
        ):
            respuesta = cliente.get(url)
            assert respuesta.status_code == 400
            assert respuesta.json()["code"] == "DATOS_INVALIDOS"
        conn.execute.assert_not_called()

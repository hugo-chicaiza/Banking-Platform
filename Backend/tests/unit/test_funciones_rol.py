"""Concesión real por función sin llamadas a WorkOS ni SQL compartido."""

import re
from dataclasses import replace
from typing import cast

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Connection

from app.core.database.db import cooperativa, seguridad
from app.core.security.auth import ROLES, require_auth, require_permiso, require_roles
from app.core.security.secciones import RUTAS_POR_SECCION
from app.main import app
from app.modules.auth import service as sesion_service
from app.modules.productos import service as productos_service
from app.modules.seguridad import funciones, service
from app.modules.seguridad.funciones_catalogo import (
    FUNCIONES,
    POR_ID,
    SECCIONES_LEGADAS,
    catalogo_valido,
    funcion_api,
)
from app.modules.seguridad.funciones_schemas import CambiosFunciones
from app.modules.seguridad.schemas import PestanasConfig
from tests.sesion import simular_sesion, usuario_con_roles
from tests.unit.test_autorizacion import ROLES_POR_RUTA


@pytest.fixture
def entorno(monkeypatch):
    ajustes = {}
    monkeypatch.setattr(funciones, "activa", lambda: True)
    monkeypatch.setattr(
        funciones, "efectivos", lambda u: funciones.resolver(ajustes, u)
    )
    yield ajustes
    app.dependency_overrides.clear()


def test_ids_de_funcion_cumplen_el_contrato_del_frontend():
    # El editor de Roles y accesos rechaza el catálogo entero si un id no cumple
    # este patrón (src/features/seguridad/api/funciones.api.ts): sin guion bajo.
    patron = re.compile(r"^[a-z][a-zA-Z0-9.]{0,79}$")
    invalidos = [
        id_
        for f in FUNCIONES
        for id_ in (f.id, *f.dependencias)
        if not patron.fullmatch(id_)
    ]
    assert not invalidos


def test_catalogo_completo_y_sin_ambiguedades():
    assert catalogo_valido()
    spec = app.openapi()["paths"]
    for funcion in FUNCIONES:
        for metodo, ruta in funcion.operaciones:
            assert metodo.lower() in spec[ruta]
            assert funcion_api(metodo, ruta) == funcion.id
    anteriores = {
        op
        for seccion, grupo in RUTAS_POR_SECCION.items()
        if seccion not in SECCIONES_LEGADAS
        for op in grupo
    }
    nuevas = {op for f in FUNCIONES for op in f.operaciones}
    plantillas = {
        op
        for f in FUNCIONES
        if f.id.startswith("contabilidad.plantillas.")
        for op in f.operaciones
    }
    assert anteriores | plantillas == nuevas
    funciones._validar_dependencias({}, set(ROLES))


def test_parametros_conserva_guardas_del_equipo(entorno, monkeypatch):
    from app.core.security import secciones

    verificadas = []
    monkeypatch.setattr(
        secciones,
        "verificar_seccion",
        lambda request, usuario: verificadas.append(True),
    )
    prueba = FastAPI()

    @prueba.get(
        "/api/v1/parametros/QA",
        dependencies=[Depends(require_auth), Depends(require_roles("ADMIN"))],
    )
    def consultar():
        return {}

    with TestClient(prueba) as cliente:
        simular_sesion(prueba, usuario_con_roles("SUPERVISOR"))
        assert cliente.get("/api/v1/parametros/QA").status_code == 403
        simular_sesion(prueba, usuario_con_roles("ADMIN"))
        assert cliente.get("/api/v1/parametros/QA").status_code == 200
    assert len(verificadas) == 2


def test_valores_iniciales_preservan_la_matriz_de_operaciones_del_equipo():
    for funcion in FUNCIONES:
        for operacion in funcion.operaciones:
            permitidos = set(ROLES_POR_RUTA[operacion]) or set(ROLES)
            if funcion.id == "contabilidad.plantillas.consultar":
                # Ampliación acordada solo de lectura; apagado rige WorkOS anterior.
                permitidos = {"ADMIN", "SUPERVISOR", "AUDITOR", "CONTADOR"}
            assert set(funcion.roles_iniciales) == permitidos, operacion


def test_resolucion_grant_revoke_y_varios_roles(entorno):
    usuario = usuario_con_roles("SUPERVISOR")
    assert "clientes.registrar" not in funciones.resolver(entorno, usuario).funciones
    entorno[("clientes.registrar", "SUPERVISOR")] = True
    assert "clientes.registrar" in funciones.resolver(entorno, usuario).funciones
    entorno[("clientes.registrar", "SUPERVISOR")] = False
    assert "clientes.registrar" not in funciones.resolver(entorno, usuario).funciones
    assert (
        "clientes.registrar"
        in funciones.resolver(
            entorno, usuario_con_roles("SUPERVISOR", "ADMIN")
        ).funciones
    )


def test_no_concede_edicion_al_conceder_consulta(entorno):
    entorno[("clientes.consultar", "AUDITOR")] = True
    permisos = funciones.resolver(entorno, usuario_con_roles("AUDITOR")).funciones
    assert "clientes.consultar" in permisos
    assert "clientes.editar" not in permisos


def test_no_confunde_ruta_fija_con_id_variable():
    assert (
        funcion_api("POST", "/api/v1/clientes/validaciones/documento")
        == "clientes.registrar"
    )
    assert (
        funcion_api("POST", "/api/v1/clientes/reincorporaciones")
        == "clientes.registrar"
    )
    assert funcion_api("GET", "/api/v1/productos/tipos") == "productos.consultar"
    assert funcion_api("POST", "/api/v1/clientes/1") is None


def test_supervisor_concedido_supera_control_rol_sin_cambiar_roles(entorno):
    prueba = FastAPI()
    router = APIRouter(dependencies=[Depends(require_auth)])

    @router.post(
        "/api/v1/clientes", dependencies=[Depends(require_roles("ASESOR", "ADMIN"))]
    )
    def registrar():
        return {"ok": True}

    prueba.include_router(router)
    usuario = usuario_con_roles("SUPERVISOR")
    simular_sesion(prueba, usuario)
    with TestClient(prueba) as cliente:
        assert cliente.post("/api/v1/clientes").status_code == 403
        entorno[("clientes.registrar", "SUPERVISOR")] = True
        assert cliente.post("/api/v1/clientes").status_code == 200
        entorno[("clientes.registrar", "SUPERVISOR")] = False
        assert cliente.post("/api/v1/clientes").status_code == 403
    assert usuario.roles == ("SUPERVISOR",)


@pytest.mark.parametrize(
    "ruta,metodo,funcion,permiso",
    [
        ("/api/v1/productos", "POST", "productos.editar", "prd-editar"),
        (
            "/api/v1/contabilidad/cuentas/importaciones",
            "POST",
            "contabilidad.importaciones.preparar",
            "con-cuenta-editar",
        ),
    ],
)
def test_concesion_sustituye_permiso_workos_equivalente(
    entorno, ruta, metodo, funcion, permiso
):
    prueba = FastAPI()
    router = APIRouter(dependencies=[Depends(require_auth)])

    @router.api_route(
        ruta, methods=[metodo], dependencies=[Depends(require_permiso(permiso))]
    )
    def operar():
        return {"ok": True}

    prueba.include_router(router)
    usuario = replace(usuario_con_roles("SUPERVISOR"), permisos=())
    simular_sesion(prueba, usuario)
    entorno[(funcion, "SUPERVISOR")] = True
    for dependencia in POR_ID[funcion].dependencias:
        entorno[(dependencia, "SUPERVISOR")] = True
    with TestClient(prueba) as cliente:
        assert cliente.request(metodo, ruta).status_code == 200
        entorno[(funcion, "SUPERVISOR")] = False
        assert cliente.request(metodo, ruta).status_code == 403
    assert usuario.permisos == ()


def test_endpoint_real_productos_usa_funcion_no_permiso_remoto(entorno, monkeypatch):
    simular_sesion(app, replace(usuario_con_roles("SUPERVISOR"), permisos=()))
    app.dependency_overrides[cooperativa] = lambda: object()
    monkeypatch.setattr(productos_service, "listar_productos", lambda conn: [])
    with TestClient(app) as cliente:
        assert cliente.get("/api/v1/productos").status_code == 200
        entorno[("productos.consultar", "SUPERVISOR")] = False
        assert cliente.get("/api/v1/productos").status_code == 403


def test_fuera_catalogo_no_se_abre_por_ser_modelo_nuevo(entorno):
    prueba = FastAPI()

    @prueba.get("/externo", dependencies=[Depends(require_roles("ADMIN"))])
    def externo():
        return {}

    simular_sesion(prueba, usuario_con_roles("SUPERVISOR"))
    with TestClient(prueba) as cliente:
        assert cliente.get("/externo").status_code == 403


def test_administracion_protegida_y_no_admin_sin_editor(entorno):
    simular_sesion(app, usuario_con_roles("SUPERVISOR"))
    app.dependency_overrides[seguridad] = lambda: object()
    with TestClient(app) as cliente:
        assert cliente.get("/api/v1/seguridad/accesos/configuracion").status_code == 403
        assert cliente.put("/api/v1/usuarios/1/roles", json={}).status_code == 403


def test_desactivado_conserva_reglas_previas(entorno, monkeypatch):
    monkeypatch.setattr(funciones, "activa", lambda: False)
    prueba = FastAPI()

    @prueba.post(
        "/api/v1/clientes", dependencies=[Depends(require_roles("ADMIN", "ASESOR"))]
    )
    def registrar():
        return {}

    simular_sesion(prueba, usuario_con_roles("SUPERVISOR"))
    entorno[("clientes.registrar", "SUPERVISOR")] = True
    with TestClient(prueba) as cliente:
        assert cliente.post("/api/v1/clientes").status_code == 403


def test_sesion_publica_funciones_y_protege_editor_anterior(entorno):
    perfil = sesion_service.perfil(usuario_con_roles("ADMIN"))
    assert perfil.autorizacion is not None
    assert "usuarios.administrar" in perfil.autorizacion.funciones
    with pytest.raises(HTTPException) as exc:
        service.guardar_pestanas(
            cast(Connection, object()),
            PestanasConfig(pestanas=[]),
            usuario_con_roles("ADMIN"),
            1,
            "127.0.0.1",
        )
    assert exc.value.status_code == 409


@pytest.mark.parametrize(
    "cambios",
    [
        [{"funcion": "no.existe", "rol": "SUPERVISOR", "permitido": True}],
        [{"funcion": "usuarios.administrar", "rol": "SUPERVISOR", "permitido": True}],
        [{"funcion": "clientes.registrar", "rol": "SUPERVISOR", "permitido": True}] * 2,
    ],
)
def test_rechaza_desconocidos_protegidos_duplicados(cambios):
    datos = CambiosFunciones.model_validate(
        {
            "version": "a" * 64,
            "motivo": "Validar configuración segura",
            "cambios": cambios,
        }
    )
    with pytest.raises(HTTPException) as exc:
        funciones._validar_cambios(datos)
    assert exc.value.status_code == 422


def test_dependencias_y_schema_estricto():
    with pytest.raises(HTTPException):
        funciones._validar_dependencias(
            {("clientes.consultar", "ASESOR"): False}, {"ASESOR"}
        )
    with pytest.raises(ValidationError):
        CambiosFunciones.model_validate(
            {
                "version": "a" * 64,
                "motivo": "Motivo válido de prueba",
                "cambios": [
                    {
                        "funcion": "clientes.registrar",
                        "rol": "SUPERVISOR",
                        "permitido": "true",
                    }
                ],
            }
        )


def test_no_acepta_guardado_interno_de_no_admin():
    datos = CambiosFunciones.model_validate(
        {
            "version": "a" * 64,
            "motivo": "Intento de guardado de prueba",
            "cambios": [
                {
                    "funcion": "clientes.registrar",
                    "rol": "SUPERVISOR",
                    "permitido": True,
                }
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        funciones.guardar(
            cast(Connection, object()), datos, usuario_con_roles("SUPERVISOR"), 1, None
        )
    assert exc.value.status_code == 403

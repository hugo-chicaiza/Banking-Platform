"""Contrato HTTP, permisos, edición parcial y auditoría de la entidad."""

from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.database.db import cooperativa
from app.core.security.auth import id_usuario_auditoria, usuario_actual
from app.modules.organizacion import repository
from app.modules.organizacion.router import router
from tests.sesion import simular_sesion, usuario_con_roles

RUTA = "/api/v1/organizacion/entidad"
DATOS_CREACION = {
    "ruc": "1790000000001",
    "razonSocial": "Cooperativa de prueba",
    "fechaConstitucion": "2000-01-01",
    "representanteLegal": "Representante de prueba",
    "identificacionRepresentante": "AB12345",
}


@pytest.fixture
def ctx(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    conn = MagicMock()
    app.dependency_overrides[cooperativa] = lambda: conn
    simular_sesion(app, usuario_con_roles("ADMIN"))
    fila = {
        "id_entidad": 1,
        "ruc": "1790000000001",
        "razon_social": "Cooperativa de prueba",
        "nombre_comercial": "Nombre de prueba",
        "tipo_organizacion": "Cooperativa de Ahorro y Credito",
        "segmento": 2,
        "numero_resolucion_seps": "SEPS-PRUEBA",
        "fecha_constitucion": date(2000, 1, 1),
        "representante_legal": "Representante de prueba",
        "identificacion_representante": "AB12345",
        "telefono": "022345678",
        "email": "entidad@example.com",
        "sitio_web": "https://example.com",
        "estado": "A",
        "fecha_registro": datetime(2026, 11, 11, 20, 15, 41),
        "modificado_por": 9,
    }
    leer = Mock(side_effect=lambda *args, **kwargs: dict(fila))

    def guardar(conexion, cambios, autor):
        fila.update(cambios, modificado_por=autor)

    escribir = Mock(side_effect=guardar)
    monkeypatch.setattr(repository, "obtener_entidad", leer)
    monkeypatch.setattr(repository, "actualizar_entidad", escribir)
    with TestClient(app) as cliente:
        yield SimpleNamespace(
            app=app, cliente=cliente, conn=conn, fila=fila, leer=leer, escribir=escribir
        )


@pytest.fixture
def ctx_creacion(ctx, monkeypatch):
    ctx.existe = False
    ctx.leer.side_effect = lambda *args, **kwargs: (
        dict(ctx.fila) if ctx.existe else None
    )

    def insertar(conexion, datos, autor):
        ctx.fila.update(datos, modificado_por=autor)
        ctx.existe = True

    ctx.insertar = Mock(side_effect=insertar)
    monkeypatch.setattr(repository, "insertar_entidad", ctx.insertar)
    return ctx


@pytest.mark.parametrize("rol", ["ASESOR", "ADMIN"])
@pytest.mark.parametrize("estado", ["A", "I"])
def test_get_devuelve_objeto_completo_para_roles_permitidos(ctx, rol, estado):
    simular_sesion(ctx.app, usuario_con_roles(rol))
    ctx.fila["estado"] = estado
    r = ctx.cliente.get(RUTA)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    datos = r.json()
    assert len(datos) == 16
    assert datos["idEntidad"] == 1
    assert datos["ruc"] == ctx.fila["ruc"]
    assert datos["numeroResolucionSeps"] == "SEPS-PRUEBA"
    assert datos["fechaConstitucion"] == "2000-01-01"
    assert datos["fechaRegistro"] == "2026-11-11T20:15:41"
    assert datos["modificadoPor"] == 9
    assert datos["estado"] == estado
    ctx.leer.assert_called_once_with(ctx.conn, bloquear=False)
    ctx.escribir.assert_not_called()


@pytest.mark.parametrize("metodo", ["get", "patch"])
def test_entidad_inexistente_responde_problem_details(ctx, metodo, eventos_auditados):
    ctx.leer.side_effect = None
    ctx.leer.return_value = None
    argumentos = {"json": {"estado": "I"}} if metodo == "patch" else {}
    r = getattr(ctx.cliente, metodo)(RUTA, **argumentos)
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["code"] == "ENTIDAD_NO_ENCONTRADA"
    assert "traceId" in r.json()
    ctx.escribir.assert_not_called()
    assert eventos_auditados == []


@pytest.mark.parametrize("metodo", ["get", "patch"])
def test_sin_sesion_rechaza_antes_de_leer(ctx, metodo):
    ctx.app.dependency_overrides.pop(usuario_actual)
    argumentos = {"json": {"estado": "I"}} if metodo == "patch" else {}
    r = getattr(ctx.cliente, metodo)(RUTA, **argumentos)
    assert r.status_code == 401
    ctx.leer.assert_not_called()
    ctx.escribir.assert_not_called()


@pytest.mark.parametrize(
    "metodo,rol",
    [("patch", "ASESOR")]
    + [
        (metodo, rol)
        for metodo in ("get", "patch")
        for rol in ("CAJERO", "SUPERVISOR", "CONTADOR", "AUDITOR")
    ],
)
def test_roles_sin_permiso_reciben_403(ctx, metodo, rol):
    simular_sesion(ctx.app, usuario_con_roles(rol))
    argumentos = {"json": {"estado": "I"}} if metodo == "patch" else {}
    r = getattr(ctx.cliente, metodo)(RUTA, **argumentos)
    assert r.status_code == 403 and r.json()["code"] == "SIN_PERMISO"
    ctx.leer.assert_not_called()
    ctx.escribir.assert_not_called()
    ctx.conn.begin.assert_not_called()


def test_patch_actualiza_solo_enviados_y_usa_autor_de_sesion(ctx, eventos_auditados):
    ctx.app.dependency_overrides.pop(id_usuario_auditoria)
    usuario = usuario_con_roles("ADMIN")
    ctx.app.dependency_overrides[usuario_actual] = lambda: replace(
        usuario, id_interno=47
    )
    r = ctx.cliente.patch(
        RUTA, json={"nombreComercial": "Otro nombre", "telefono": None}
    )
    assert r.status_code == 200, r.text
    assert r.json()["nombreComercial"] == "Otro nombre"
    assert r.json()["telefono"] is None
    assert r.json()["razonSocial"] == "Cooperativa de prueba"
    assert r.json()["fechaRegistro"] == "2026-11-11T20:15:41"
    assert r.json()["modificadoPor"] == 47
    ctx.escribir.assert_called_once_with(
        ctx.conn, {"nombre_comercial": "Otro nombre", "telefono": None}, 47
    )
    assert ctx.leer.call_args_list[0].kwargs == {"bloquear": True}
    ctx.conn.begin.return_value.__exit__.assert_called_once_with(None, None, None)
    assert len(eventos_auditados) == 1
    evento = eventos_auditados[0]
    assert evento.accion == "EDITAR_ENTIDAD" and evento.id_registro == "1"
    assert "nombre_comercial,telefono" in evento.descripcion
    assert "Otro nombre" not in evento.descripcion
    assert ctx.fila["ruc"] not in evento.descripcion


@pytest.mark.parametrize(
    "campo",
    [
        "nombreComercial",
        "segmento",
        "numeroResolucionSeps",
        "telefono",
        "email",
        "sitioWeb",
    ],
)
def test_null_limpia_campos_anulables(ctx, campo):
    r = ctx.cliente.patch(RUTA, json={campo: None})
    assert r.status_code == 200, r.text
    assert r.json()[campo] is None


def test_repetir_valores_actuales_conserva_autor_y_auditoria(ctx, eventos_auditados):
    for _ in range(2):
        r = ctx.cliente.patch(RUTA, json={"estado": "A", "telefono": "022345678"})
        assert r.status_code == 200 and r.json()["modificadoPor"] == 9
    ctx.escribir.assert_not_called()
    assert eventos_auditados == []


def test_edicion_completa_de_campos_editables(ctx):
    datos = {
        "ruc": "0990000000001",
        "razonSocial": "Nueva razón social",
        "nombreComercial": "Nueva marca",
        "tipoOrganizacion": "Otra organización",
        "segmento": 5,
        "numeroResolucionSeps": "SEPS-NUEVA",
        "fechaConstitucion": "1999-12-31",
        "representanteLegal": "Otro representante",
        "identificacionRepresentante": "ABC1234567890",
        "telefono": "0999999999",
        "email": "nueva@example.com",
        "sitioWeb": "https://example.org",
        "estado": "I",
    }
    r = ctx.cliente.patch(RUTA, json=datos)
    assert r.status_code == 200, r.text
    assert {campo: r.json()[campo] for campo in datos} == datos
    assert ctx.escribir.call_args.args[1]["fecha_constitucion"] == date(1999, 12, 31)


@pytest.mark.parametrize(
    "campo",
    [
        "ruc",
        "razonSocial",
        "tipoOrganizacion",
        "fechaConstitucion",
        "representanteLegal",
        "identificacionRepresentante",
        "estado",
    ],
)
def test_null_rechazado_para_campos_obligatorios(ctx, campo):
    r = ctx.cliente.patch(RUTA, json={campo: None})
    assert r.status_code == 400 and r.json()["code"] == "DATOS_INVALIDOS"
    ctx.leer.assert_not_called()
    ctx.escribir.assert_not_called()


@pytest.mark.parametrize(
    "datos",
    [
        {},
        {"idEntidad": 1},
        {"fechaRegistro": "2026-01-01T00:00:00"},
        {"modificadoPor": 77},
        {"estado": "I", "desconocido": "valor"},
        {"ruc": "1790000000002"},
        {"ruc": "179000000001"},
        {"ruc": "A790000000001"},
        {"ruc": "１７９０００００００００１"},
        {"ruc": 1790000000001},
        {"estado": "C"},
        {"estado": "a"},
        {"segmento": 0},
        {"segmento": 6},
        {"segmento": True},
        {"segmento": 1.5},
        {"segmento": "2"},
        {"identificacionRepresentante": "AB12"},
        {"identificacionRepresentante": "AB123456789012"},
        {"identificacionRepresentante": "ab123"},
        {"identificacionRepresentante": "AB-123"},
        {"fechaConstitucion": "2026-02-30"},
    ]
    + [
        {campo: texto}
        for campo in ("razonSocial", "tipoOrganizacion", "representanteLegal")
        for texto in ("", "   ")
    ],
)
def test_body_invalido_se_rechaza_antes_de_sql(ctx, datos):
    r = ctx.cliente.patch(RUTA, json=datos)
    assert r.status_code == 400 and r.json()["code"] == "DATOS_INVALIDOS", r.text
    ctx.leer.assert_not_called()
    ctx.escribir.assert_not_called()
    ctx.conn.begin.assert_not_called()


@pytest.mark.parametrize(
    "campo,limite",
    [
        ("razonSocial", 250),
        ("nombreComercial", 150),
        ("tipoOrganizacion", 60),
        ("numeroResolucionSeps", 60),
        ("representanteLegal", 250),
        ("telefono", 15),
        ("email", 150),
        ("sitioWeb", 150),
    ],
)
def test_longitudes_maximas(ctx, campo, limite):
    assert ctx.cliente.patch(RUTA, json={campo: "X" * limite}).status_code == 200
    ctx.escribir.reset_mock()
    r = ctx.cliente.patch(RUTA, json={campo: "X" * (limite + 1)})
    assert r.status_code == 400 and r.json()["code"] == "DATOS_INVALIDOS"
    ctx.escribir.assert_not_called()


@pytest.mark.parametrize("metodo", ["get", "patch"])
def test_rechaza_parametros_de_consulta(ctx, metodo):
    argumentos = {"json": {"estado": "I"}} if metodo == "patch" else {}
    r = getattr(ctx.cliente, metodo)(RUTA + "?idEntidad=2", **argumentos)
    assert r.status_code == 400 and r.json()["code"] == "PARAMETRO_INVALIDO"
    ctx.leer.assert_not_called()
    ctx.escribir.assert_not_called()


def test_error_sql_revierte_y_evitar_auditoria_de_exito(ctx, eventos_auditados):
    ctx.escribir.side_effect = SQLAlchemyError("fallo simulado")
    r = ctx.cliente.patch(RUTA, json={"estado": "I"})
    assert r.status_code == 500 and r.json()["code"] == "ERROR_INTERNO"
    assert ctx.conn.begin.return_value.__exit__.call_args.args[0] is SQLAlchemyError
    assert eventos_auditados == []


def test_error_commit_evitar_auditoria_de_exito(ctx, eventos_auditados):
    ctx.conn.begin.return_value.__exit__.side_effect = SQLAlchemyError("fallo commit")
    r = ctx.cliente.patch(RUTA, json={"estado": "I"})
    assert r.status_code == 500
    assert eventos_auditados == []


def test_openapi_documenta_roles_contrato_y_etiqueta(ctx):
    documento = ctx.app.openapi()
    rutas = documento["paths"][RUTA]
    assert set(rutas) == {"get", "post", "patch"}
    assert rutas["get"]["x-roles"] == ["ASESOR", "ADMIN"]
    assert rutas["patch"]["x-roles"] == ["ADMIN"]
    assert rutas["post"]["x-roles"] == ["ADMIN"]
    assert rutas["get"]["operationId"] == "EntidadObtener"
    assert rutas["patch"]["operationId"] == "EntidadEditar"
    assert rutas["post"]["operationId"] == "EntidadCrear"
    assert "201" in rutas["post"]["responses"]
    for operacion in rutas.values():
        assert operacion["tags"] == ["Organización"]
        assert operacion["security"]
        assert "application/problem+json" in operacion["responses"]["400"]["content"]
    esquema = documento["components"]["schemas"]["EntidadUpdate"]
    assert esquema["additionalProperties"] is False
    assert esquema["minProperties"] == 1
    assert (
        not {"idEntidad", "fechaRegistro", "modificadoPor"}
        & esquema["properties"].keys()
    )
    assert esquema["properties"]["razonSocial"]["type"] == "string"
    assert esquema["properties"]["segmento"]["anyOf"][1]["type"] == "null"
    assert "/api/v1/agencias/{id_agencia}/estado" in documento["paths"]
    creacion = documento["components"]["schemas"]["EntidadCreate"]
    assert set(creacion["required"]) == set(DATOS_CREACION)
    assert creacion["additionalProperties"] is False
    assert (
        not {"idEntidad", "fechaRegistro", "modificadoPor"}
        & creacion["properties"].keys()
    )


def test_post_admin_crea_con_defaults_y_autor_de_sesion(
    ctx_creacion, eventos_auditados
):
    ctx = ctx_creacion
    ctx.app.dependency_overrides.pop(id_usuario_auditoria)
    usuario = replace(usuario_con_roles("ADMIN"), id_interno=47)
    ctx.app.dependency_overrides[usuario_actual] = lambda: usuario

    r = ctx.cliente.post(RUTA, json=DATOS_CREACION)

    assert r.status_code == 201, r.text
    respuesta = r.json()
    assert respuesta["idEntidad"] == 1 and respuesta["modificadoPor"] == 47
    assert respuesta["tipoOrganizacion"] == "Cooperativa de Ahorro y Credito"
    assert respuesta["estado"] == "A"
    for campo in (
        "nombreComercial",
        "segmento",
        "numeroResolucionSeps",
        "telefono",
        "email",
        "sitioWeb",
    ):
        assert respuesta[campo] is None
    assert {campo: respuesta[campo] for campo in DATOS_CREACION} == DATOS_CREACION
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    ctx.insertar.assert_called_once()
    assert ctx.insertar.call_args.args[2] == 47
    assert ctx.insertar.call_args.args[1]["fecha_constitucion"] == date(2000, 1, 1)
    assert (
        not {"id_entidad", "fecha_registro", "modificado_por"}
        & ctx.insertar.call_args.args[1].keys()
    )
    assert ctx.leer.call_args_list[0].kwargs == {"bloquear": True}
    ctx.conn.begin.return_value.__exit__.assert_called_once_with(None, None, None)
    assert len(eventos_auditados) == 1
    evento = eventos_auditados[0]
    assert evento.accion == "CREAR_ENTIDAD" and evento.id_registro == "1"
    assert evento.resultado == "Exitoso"
    assert DATOS_CREACION["ruc"] not in evento.descripcion
    assert DATOS_CREACION["representanteLegal"] not in evento.descripcion


def test_post_admite_campos_opcionales_y_estado_inactivo(ctx_creacion):
    datos = DATOS_CREACION | {
        "nombreComercial": "Nueva marca",
        "tipoOrganizacion": "Otra organización",
        "segmento": 5,
        "numeroResolucionSeps": "SEPS-PRUEBA",
        "telefono": "0999999999",
        "email": "nueva@example.com",
        "sitioWeb": None,
        "estado": "I",
    }
    r = ctx_creacion.cliente.post(RUTA, json=datos)
    assert r.status_code == 201, r.text
    assert {campo: r.json()[campo] for campo in datos} == datos


@pytest.mark.parametrize(
    "rol", [None, "ASESOR", "CAJERO", "SUPERVISOR", "CONTADOR", "AUDITOR", ""]
)
def test_post_exclusivo_admin(ctx_creacion, rol):
    ctx = ctx_creacion
    if rol is None:
        ctx.app.dependency_overrides.pop(usuario_actual)
    else:
        simular_sesion(ctx.app, usuario_con_roles(rol))
    r = ctx.cliente.post(RUTA, json=DATOS_CREACION)
    assert r.status_code == (401 if rol is None else 403)
    ctx.leer.assert_not_called()
    ctx.insertar.assert_not_called()
    ctx.conn.begin.assert_not_called()


@pytest.mark.parametrize("campo", list(DATOS_CREACION))
def test_post_exige_campos_obligatorios(ctx_creacion, campo):
    datos = {
        nombre: valor for nombre, valor in DATOS_CREACION.items() if nombre != campo
    }
    r = ctx_creacion.cliente.post(RUTA, json=datos)
    assert r.status_code == 400 and r.json()["code"] == "DATOS_INVALIDOS"
    assert any(error["field"] == campo for error in r.json()["errors"])
    ctx_creacion.insertar.assert_not_called()
    ctx_creacion.leer.assert_not_called()


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("ruc", "1790000000002"),
        ("ruc", "A790000000001"),
        ("razonSocial", "   "),
        ("razonSocial", "X" * 251),
        ("representanteLegal", ""),
        ("representanteLegal", "X" * 251),
        ("identificacionRepresentante", "ab123"),
        ("identificacionRepresentante", "AB12"),
        ("nombreComercial", "X" * 151),
        ("tipoOrganizacion", "X" * 61),
        ("segmento", 0),
        ("segmento", 6),
        ("segmento", True),
        ("numeroResolucionSeps", "X" * 61),
        ("telefono", "X" * 16),
        ("email", "X" * 151),
        ("sitioWeb", "X" * 151),
        ("fechaConstitucion", "2026-02-30"),
        ("estado", "C"),
        ("idEntidad", 1),
        ("fechaRegistro", "2026-01-01T00:00:00"),
        ("modificadoPor", 47),
    ]
    + [(campo, None) for campo in (*DATOS_CREACION, "tipoOrganizacion", "estado")],
)
def test_post_valida_contrato_antes_de_sql(ctx_creacion, campo, valor):
    r = ctx_creacion.cliente.post(RUTA, json=DATOS_CREACION | {campo: valor})
    assert r.status_code == 400 and r.json()["code"] == "DATOS_INVALIDOS", r.text
    assert any(error["field"] == campo for error in r.json()["errors"])
    ctx_creacion.leer.assert_not_called()
    ctx_creacion.insertar.assert_not_called()


def test_post_repetido_o_existente_responde_conflicto(ctx_creacion, eventos_auditados):
    ctx = ctx_creacion
    primero = ctx.cliente.post(RUTA, json=DATOS_CREACION)
    assert primero.status_code == 201
    for datos in (DATOS_CREACION, DATOS_CREACION | {"razonSocial": "Otra entidad"}):
        r = ctx.cliente.post(RUTA, json=datos)
        assert r.status_code == 409 and r.json()["code"] == "ENTIDAD_YA_EXISTE"
    assert ctx.cliente.get(RUTA).json() == primero.json()
    ctx.insertar.assert_called_once()
    assert len(eventos_auditados) == 1


@pytest.mark.parametrize("fallo", ["insertar", "commit"])
def test_post_fallido_revierte_y_evitar_auditoria_de_exito(
    ctx_creacion, eventos_auditados, fallo
):
    ctx = ctx_creacion
    if fallo == "insertar":
        ctx.insertar.side_effect = SQLAlchemyError("fallo INSERT")
    else:
        ctx.conn.begin.return_value.__exit__.side_effect = SQLAlchemyError(
            "fallo commit"
        )
    r = ctx.cliente.post(RUTA, json=DATOS_CREACION)
    assert r.status_code == 500 and r.json()["code"] == "ERROR_INTERNO"
    assert eventos_auditados == []
    ctx.conn.begin.return_value.__exit__.assert_called_once()


def test_post_rechaza_parametros_de_consulta(ctx_creacion):
    r = ctx_creacion.cliente.post(RUTA + "?idEntidad=1", json=DATOS_CREACION)
    assert r.status_code == 400 and r.json()["code"] == "PARAMETRO_INVALIDO"
    ctx_creacion.leer.assert_not_called()
    ctx_creacion.insertar.assert_not_called()


def test_metodo_anterior_de_creacion_responde_405(ctx_creacion):
    r = ctx_creacion.cliente.request("PUT", RUTA, json=DATOS_CREACION)
    assert r.status_code == 405
    ctx_creacion.leer.assert_not_called()
    ctx_creacion.insertar.assert_not_called()

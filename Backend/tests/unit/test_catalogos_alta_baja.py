"""Alta, baja y auditoría con antes y después en los catálogos (E1-09 #109), sin BD."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.core.database.db import cooperativa
from app.core.security import audit
from app.modules.catalogos import administracion
from app.modules.catalogos.router import router
from tests.sesion import simular_sesion, usuario_con_roles

BASE = "https://testserver/api/v1/catalogos/administracion"
EVENTOS: list[audit.EventoAuditoria] = []


class Conexion:
    """Filas en memoria por catálogo; responde a INSERT, «en uso» y DELETE."""

    def __init__(self) -> None:
        self.filas: dict[str, list[dict[str, Any]]] = {
            "seguros": [],
            "ciudades": [
                {
                    "id": "7",
                    "estado": "A",
                    "codigoPais": "ECU",
                    "provincia": "Pichincha",
                    "nombre": "Quito",
                }
            ],
        }
        self.en_uso = False
        self.duplicado = False
        self.borrados: list[str] = []

    def execute(self, sql: Any, params: dict[str, Any]) -> Any:
        texto = str(sql)
        r = MagicMock()
        if "INSERT INTO Credito.Seguro" in texto:
            if self.duplicado:
                raise DBAPIError(
                    "INSERT",
                    {},
                    Exception("Violation of UNIQUE KEY 'UQ_Seguro_Codigo'. (2627)"),
                )
            self.filas["seguros"].append(
                {
                    "id": "9",
                    "estado": "A",
                    **{k: v for k, v in params.items() if k != "vigenciaDesde"},
                }
            )
            r.scalar_one.return_value = r.scalar.return_value = "9"
        elif "CASE WHEN EXISTS" in texto:
            r.scalar_one.return_value = 1 if self.en_uso else 0
        elif texto.lstrip().startswith("DELETE"):
            self.borrados.append(params["id"])
        else:  # UPDATE de la edición
            for f in self.filas["ciudades"]:
                if f["id"] == params["id"]:
                    f.update({k: params[k] for k in f if params.get(f"c_{k}")})
        return r

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@pytest.fixture
def bd(monkeypatch: pytest.MonkeyPatch) -> Conexion:
    conn = Conexion()
    sql_a_clave = {c.listar: c.clave for c in administracion.CATALOGOS.values()}
    monkeypatch.setattr(
        administracion,
        "_rows",
        lambda _c, sql: [dict(f) for f in conn.filas.get(sql_a_clave[sql], [])],
    )
    EVENTOS.clear()
    monkeypatch.setattr(administracion, "_opciones_dinamicas", lambda _c, _o: [])
    monkeypatch.setattr(audit, "registrar", EVENTOS.append)
    return conn


def _cliente(conn: Conexion, *roles: str) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[cooperativa] = lambda: conn
    simular_sesion(app, usuario_con_roles(*roles))
    return TestClient(app, raise_server_exceptions=False)


SEGURO = {
    "codigo": "vida01",
    "nombre": "Seguro de vida",
    "aseguradora": None,
    "tipoCalculo": "Fijo",
    "valor": 1.5,
    "vigenciaDesde": "2026-12-01",
}


def test_descriptor_dice_que_se_crea_y_que_se_elimina(bd):
    d = {c["clave"]: c for c in _cliente(bd, "ASESOR").get(BASE).json()}
    assert [c["nombre"] for c in d["seguros"]["camposAlta"]][:2] == ["codigo", "nombre"]
    assert d["denominaciones"]["camposAlta"][0]["opciones"] == ["Billete", "Moneda"]
    assert (
        d["tasas-interes"]["camposAlta"] == [] and not d["canales"]["permiteEliminar"]
    )
    assert d["ciudades"]["permiteEliminar"]


def test_alta_con_codigo_en_mayusculas_y_auditada(bd):
    admin = _cliente(bd, "ADMIN")
    assert (
        _cliente(bd, "ASESOR").post(f"{BASE}/seguros", json=SEGURO).status_code == 403
    )
    r = admin.post(f"{BASE}/seguros", json=SEGURO)
    assert r.status_code == 201, r.text
    assert r.json()["codigo"] == "VIDA01"
    assert (
        EVENTOS[-1].accion == "CREAR" and '"codigo":"VIDA01"' in EVENTOS[-1].descripcion
    )


def test_codigo_duplicado_es_409(bd):
    bd.duplicado = True
    r = _cliente(bd, "ADMIN").post(f"{BASE}/seguros", json=SEGURO)
    assert r.status_code == 409 and r.json()["code"] == "CODIGO_DUPLICADO"


@pytest.mark.parametrize(
    ("clave", "cuerpo", "status", "codigo"),
    [
        ("tasas-interes", {}, 422, "ALTA_NO_PERMITIDA"),  # se crean con su propio POST
        ("seguros", {**SEGURO, "tipoCalculo": "Otro"}, 422, "DATOS_INVALIDOS"),
        (
            "seguros",
            {**SEGURO, "tipoCalculo": "Porcentaje", "valor": 150},
            422,
            "DATOS_INVALIDOS",
        ),
        ("seguros", {**SEGURO, "codigo": "a b"}, 422, "DATOS_INVALIDOS"),
        ("seguros", {**SEGURO, "extra": 1}, 400, "DATOS_INVALIDOS"),
        (
            "paises",
            {"codigoPais": "EC", "codigoNumerico": "218", "nombrePais": "X"},
            422,
            "DATOS_INVALIDOS",
        ),
        ("agencias", {}, 404, "CATALOGO_NO_EXISTE"),
    ],
)
def test_alta_invalida(bd, clave, cuerpo, status, codigo):
    r = _cliente(bd, "ADMIN").post(f"{BASE}/{clave}", json=cuerpo)
    assert r.status_code == status and r.json()["code"] == codigo, r.text


def test_baja_solo_sin_uso(bd):
    admin = _cliente(bd, "ADMIN")
    bd.en_uso = True
    r = admin.delete(f"{BASE}/ciudades/7")
    assert r.status_code == 409 and r.json()["code"] == "ITEM_EN_USO"
    assert bd.borrados == []
    bd.en_uso = False
    assert admin.delete(f"{BASE}/ciudades/7").status_code == 204
    assert bd.borrados == ["7"]
    assert (
        EVENTOS[-1].accion == "ELIMINAR"
        and '"nombre":"Quito"' in EVENTOS[-1].descripcion
    )
    # Canales pide el código antes que nada; sin él, 428
    r = admin.delete(f"{BASE}/canales/1")
    assert r.status_code == 428 and r.json()["code"] == "CONFIRMACION_REQUERIDA"
    assert admin.delete(f"{BASE}/ciudades/99").status_code == 404


def test_edicion_audita_antes_y_despues(bd):
    r = _cliente(bd, "ADMIN").patch(
        f"{BASE}/ciudades/7", json={"nombre": "San Francisco de Quito"}
    )
    assert r.status_code == 200, r.text
    descripcion = EVENTOS[-1].descripcion
    assert 'antes={"nombre":"Quito"}' in descripcion
    assert 'despues={"nombre":"San Francisco de Quito"}' in descripcion

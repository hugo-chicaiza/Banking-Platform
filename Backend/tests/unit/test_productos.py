"""Productos y subproductos (/api/v1/productos), sin BD.

El repositorio se reemplaza por un almacén en memoria con las restricciones reales:
UQ_Producto_Codigo, UQ_SubProducto_Codigo, Estado A/I, TipoCuenta solo en Cuenta.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.core.database.db import cooperativa
from app.core.security import audit
from app.core.security.auth import ROLES
from app.modules.productos import repository as repo
from app.modules.productos.router import router
from tests.sesion import simular_sesion, usuario_con_roles

BASE = "https://testserver/api/v1/productos"


def _duplicado(restriccion: str) -> DBAPIError:
    mensaje = f"Violation of UNIQUE KEY constraint '{restriccion}'. (2627)"
    return DBAPIError("INSERT ...", {}, Exception(mensaje))


@dataclass
class BdFalsa:
    productos: dict[int, dict[str, Any]] = field(default_factory=dict)
    subs: dict[int, dict[str, Any]] = field(default_factory=dict)
    redes: set[int] = field(default_factory=lambda: {2})
    tipos_credito: set[int] = field(default_factory=lambda: {1})
    siguiente: int = 10

    def _producto(self, id_: int) -> dict[str, Any] | None:
        p = self.productos.get(id_)
        return dict(p) if p else None

    def obtener(self, _c: Any, id_: int, *, bloquear: bool = False) -> Any:
        return self._producto(id_)

    def listar(self, _c: Any) -> list[dict[str, Any]]:
        return [dict(p) for p in self.productos.values()]

    def listar_subs(
        self, _c: Any, id_producto: int | None = None
    ) -> list[dict[str, Any]]:
        return [
            dict(s)
            for s in self.subs.values()
            if id_producto in (None, s["id_producto"])
        ]

    def obtener_sub(self, _c: Any, id_: int, *, bloquear: bool = False) -> Any:
        s = self.subs.get(id_)
        return dict(s) if s else None

    def insertar(self, _c: Any, d: dict[str, Any]) -> int:
        if any(
            p["codigo_producto"] == d["codigo_producto"]
            for p in self.productos.values()
        ):
            raise _duplicado("UQ_Producto_Codigo")
        self.siguiente += 1
        self.productos[self.siguiente] = {
            "id_producto": self.siguiente,
            "codigo_producto": d["codigo_producto"],
            "nombre_producto": d["nombre_producto"],
            "descripcion": d["descripcion"],
            "tipo_producto": d["tipo_producto"],
            "tipo_cuenta": d["tipo_cuenta"],
            "monto_apertura_minimo": d["monto_apertura_minimo"]
            if d["tipo_producto"] == "Cuenta"
            else None,
            "id_tipo_credito": d["id_tipo_credito"],
            "nombre_tipo_credito": "Consumo" if d["id_tipo_credito"] else None,
            "id_red": d["id_red"],
            "nombre_red": "Mastercard" if d["id_red"] else None,
            "permite_operaciones_presenciales": d["permite_operaciones_presenciales"],
            "estado": "I",
        }
        return self.siguiente

    def actualizar(self, _c: Any, id_: int, cambios: dict[str, Any]) -> None:
        self.productos[id_].update(cambios)

    def insertar_sub(self, _c: Any, id_producto: int, codigo: str, nombre: str) -> int:
        if any(s["codigo_sub_producto"] == codigo for s in self.subs.values()):
            raise _duplicado("UQ_SubProducto_Codigo")
        self.siguiente += 1
        self.subs[self.siguiente] = {
            "id_sub_producto": self.siguiente,
            "id_producto": id_producto,
            "codigo_sub_producto": codigo,
            "nombre_sub_producto": nombre,
            "estado": "A",
            "fecha_registro": datetime(2026, 11, 15, 10, 0),
        }
        return self.siguiente

    def actualizar_sub(self, _c: Any, id_: int, cambios: dict[str, Any]) -> None:
        self.subs[id_].update(cambios)


@pytest.fixture
def bd(monkeypatch: pytest.MonkeyPatch) -> BdFalsa:
    falsa = BdFalsa()
    for nombre, funcion in {
        "obtener_producto": falsa.obtener,
        "listar_productos": falsa.listar,
        "listar_subproductos": falsa.listar_subs,
        "obtener_subproducto": falsa.obtener_sub,
        "insertar_producto": falsa.insertar,
        "actualizar_producto": falsa.actualizar,
        "insertar_subproducto": falsa.insertar_sub,
        "actualizar_subproducto": falsa.actualizar_sub,
        "existe_red_activa": lambda _c, i: i in falsa.redes,
        "existe_tipo_credito_activo": lambda _c, i: i in falsa.tipos_credito,
    }.items():
        monkeypatch.setattr(repo, nombre, funcion)
    return falsa


@pytest.fixture
def eventos(monkeypatch: pytest.MonkeyPatch) -> list[audit.EventoAuditoria]:
    lista: list[audit.EventoAuditoria] = []
    monkeypatch.setattr(audit, "registrar", lista.append)
    return lista


def _cliente(*roles: str) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[cooperativa] = lambda: MagicMock()
    simular_sesion(app, usuario_con_roles(*roles))
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin() -> Iterator[TestClient]:
    yield _cliente("ADMIN")


@pytest.fixture
def asesor() -> Iterator[TestClient]:
    yield _cliente("ASESOR")


AHORRO = {
    "codigoProducto": "AHO002",
    "nombreProducto": "Ahorro programado",
    "descripcion": "Ahorro con meta y plazo",
    "tipoProducto": "Cuenta",
    "tipoCuenta": "Ahorro",
    "montoAperturaMinimo": 10,
}


def test_admin_crea_producto_inactivo_con_descripcion(bd, admin, eventos):
    r = admin.post(BASE, json=AHORRO)
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "I"
    assert cuerpo["descripcion"] == "Ahorro con meta y plazo"
    assert cuerpo["subproductos"] == []
    assert eventos[-1].resultado == "Exitoso" and eventos[-1].accion == "CREAR"


def test_asesor_consulta_pero_no_crea(bd, asesor):
    assert asesor.get(BASE).status_code == 200
    r = asesor.post(BASE, json=AHORRO)
    assert r.status_code == 403


@pytest.mark.parametrize("rol", [r for r in ROLES if r not in ("ADMIN", "ASESOR")])
def test_otros_roles_no_consultan(bd, rol):
    assert _cliente(rol).get(BASE).status_code == 403


def test_codigo_duplicado_es_409(bd, admin):
    assert admin.post(BASE, json=AHORRO).status_code == 201
    r = admin.post(BASE, json=AHORRO)
    assert r.status_code == 409 and r.json()["code"] == "CODIGO_DUPLICADO"


@pytest.mark.parametrize(
    ("cuerpo", "status"),
    [
        ({**AHORRO, "tipoCuenta": None}, 422),  # Cuenta sin tipo de cuenta
        ({**AHORRO, "idRed": 2}, 422),  # campo de Tarjeta en una Cuenta
        ({**AHORRO, "estado": "A"}, 422),  # el estado no se elige al crear
        ({**AHORRO, "codigoProducto": "a$"}, 422),
        ({**AHORRO, "descripcion": "línea\u0001oculta"}, 422),
        (
            {
                "codigoProducto": "CRE009",
                "nombreProducto": "Crédito X",
                "tipoProducto": "Credito",
            },
            422,
        ),
    ],
)
def test_validaciones_de_entrada(bd, admin, cuerpo, status):
    assert admin.post(BASE, json=cuerpo).status_code in (400, status)


def test_red_inexistente(bd, admin):
    r = admin.post(
        BASE,
        json={
            "codigoProducto": "TAR009",
            "nombreProducto": "Tarjeta X",
            "tipoProducto": "Tarjeta",
            "idRed": 99,
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "RED_NO_EXISTE"


def test_activar_exige_subproducto_y_luego_se_activa(bd, admin):
    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    r = admin.patch(f"{BASE}/{id_}", json={"estado": "A"})
    assert r.status_code == 409 and r.json()["code"] == "PRODUCTO_SIN_SUBPRODUCTOS"
    s = admin.post(
        f"{BASE}/{id_}/subproductos",
        json={
            "codigoSubProducto": "AHO002-PN",
            "nombreSubProducto": "Programado natural",
        },
    )
    assert s.status_code == 201 and s.json()["estado"] == "A"
    r = admin.patch(f"{BASE}/{id_}", json={"estado": "A", "descripcion": None})
    assert r.status_code == 200
    assert r.json()["estado"] == "A" and r.json()["descripcion"] is None
    assert len(r.json()["subproductos"]) == 1


def test_codigo_y_tipo_no_se_editan(bd, admin):
    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    assert admin.patch(
        f"{BASE}/{id_}", json={"codigoProducto": "OTRO1"}
    ).status_code in (400, 422)
    assert admin.patch(
        f"{BASE}/{id_}", json={"tipoProducto": "Credito"}
    ).status_code in (400, 422)


def test_monto_solo_en_cuenta(bd, admin):
    id_ = admin.post(
        BASE,
        json={
            "codigoProducto": "TAR009",
            "nombreProducto": "Tarjeta X",
            "tipoProducto": "Tarjeta",
            "idRed": 2,
        },
    ).json()["idProducto"]
    r = admin.patch(f"{BASE}/{id_}", json={"montoAperturaMinimo": 5})
    assert r.status_code == 422 and r.json()["code"] == "CAMPO_NO_APLICA"


def test_subproducto_de_tarjeta_sigue_la_convencion(bd, admin):
    id_ = admin.post(
        BASE,
        json={
            "codigoProducto": "TAR009",
            "nombreProducto": "Tarjeta X",
            "tipoProducto": "Tarjeta",
            "idRed": 2,
        },
    ).json()["idProducto"]
    r = admin.post(
        f"{BASE}/{id_}/subproductos",
        json={"codigoSubProducto": "XYZ-MC", "nombreSubProducto": "Sin prefijo"},
    )
    assert r.status_code == 422 and r.json()["code"] == "CODIGO_TARJETA_INVALIDO"
    r = admin.post(
        f"{BASE}/{id_}/subproductos",
        json={"codigoSubProducto": "TDB009-MC", "nombreSubProducto": "Débito X"},
    )
    assert r.status_code == 201 and r.json()["tipoTarjeta"] == "Debito"


def test_desactivar_subproducto(bd, admin, asesor):
    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    sub = admin.post(
        f"{BASE}/{id_}/subproductos",
        json={
            "codigoSubProducto": "AHO002-PN",
            "nombreSubProducto": "Programado natural",
        },
    ).json()
    assert (
        asesor.patch(
            f"{BASE}/subproductos/{sub['idSubProducto']}", json={"estado": "I"}
        ).status_code
        == 403
    )
    r = admin.patch(f"{BASE}/subproductos/{sub['idSubProducto']}", json={"estado": "I"})
    assert r.status_code == 200 and r.json()["estado"] == "I"


def test_producto_inexistente(bd, admin):
    assert admin.get(f"{BASE}/999").status_code == 404
    assert (
        admin.post(
            f"{BASE}/999/subproductos",
            json={"codigoSubProducto": "AAA-1", "nombreSubProducto": "Nada"},
        ).status_code
        == 404
    )


def test_parametros_de_consulta_desconocidos(bd, asesor):
    assert asesor.get(f"{BASE}?estado=A").status_code == 400

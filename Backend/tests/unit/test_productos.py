"""Productos y subproductos (/api/v1/productos), sin BD.

El repositorio se reemplaza por un almacén en memoria con las restricciones reales:
UQ_Producto_Codigo, UQ_SubProducto_Codigo, Estado A/I, TipoCuenta solo en Cuenta.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.core.database.db import cooperativa
from app.core.security import audit
from app.core.security.auth import ROLES
from app.core.security.permisos import PERMISOS
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
    en_uso: set[int] = field(default_factory=set)
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
            "estado_catalogo": "Borrador",
        }
        return self.siguiente

    def actualizar(self, _c: Any, id_: int, cambios: dict[str, Any]) -> None:
        self.productos[id_].update(cambios)

    def insertar_sub(
        self,
        _c: Any,
        id_producto: int,
        codigo: str,
        nombre: str,
        edad_minima: int | None = None,
        edad_maxima: int | None = None,
        **elegibilidad: Any,
    ) -> int:
        if any(s["codigo_sub_producto"] == codigo for s in self.subs.values()):
            raise _duplicado("UQ_SubProducto_Codigo")
        self.siguiente += 1
        self.subs[self.siguiente] = {
            "id_sub_producto": self.siguiente,
            "id_producto": id_producto,
            "codigo_sub_producto": codigo,
            "nombre_sub_producto": nombre,
            "estado": "I",
            "estado_catalogo": "Borrador",
            **elegibilidad,
            "fecha_registro": datetime(2026, 11, 15, 10, 0),
            "edad_minima": edad_minima,
            "edad_maxima": edad_maxima,
        }
        return self.siguiente

    def actualizar_sub(self, _c: Any, id_: int, cambios: dict[str, Any]) -> None:
        self.subs[id_].update(cambios)


@pytest.fixture
def bd(monkeypatch: pytest.MonkeyPatch) -> BdFalsa:
    falsa = BdFalsa()
    for nombre, funcion in {
        "listar_tipos": lambda _c: [
            {
                "id_tipo_producto": 1,
                "codigo": "CUENTA_AHORRO",
                "nombre": "Cuenta de ahorro",
                "tipo_producto": "Cuenta",
                "tipo_cuenta": "Ahorro",
            },
            {
                "id_tipo_producto": 4,
                "codigo": "CREDITO",
                "nombre": "Credito",
                "tipo_producto": "Credito",
                "tipo_cuenta": None,
            },
            {
                "id_tipo_producto": 5,
                "codigo": "TARJETA",
                "nombre": "Tarjeta",
                "tipo_producto": "Tarjeta",
                "tipo_cuenta": None,
            },
        ],
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
        "producto_en_uso": lambda _c, i: i in falsa.en_uso,
        "eliminar_producto": lambda _c, i: falsa.productos.pop(i),
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


@pytest.mark.parametrize(
    "rol", [r for r in ROLES if r not in PERMISOS["prd-consultar"]]
)
def test_sin_prd_consultar_no_consultan(bd, rol):
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
    assert s.status_code == 201 and s.json()["estado"] == "I"
    r = admin.patch(f"{BASE}/{id_}", json={"estado": "A", "descripcion": None})
    assert r.status_code == 200
    assert r.json()["estado"] == "A" and r.json()["descripcion"] is None
    assert len(r.json()["subproductos"]) == 1


def test_codigo_solo_se_edita_en_borrador_y_el_tipo_nunca(bd, admin):
    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    # Inactivo y sin uso: el código se corrige
    r = admin.patch(f"{BASE}/{id_}", json={"codigoProducto": "AHO003"})
    assert r.status_code == 200 and bd.productos[id_]["codigo_producto"] == "AHO003"
    # Usado o activo: 409 PRODUCTO_NO_EDITABLE (E3-02 AC 4)
    bd.en_uso.add(id_)
    r = admin.patch(f"{BASE}/{id_}", json={"codigoProducto": "AHO004"})
    assert r.status_code == 409 and r.json()["code"] == "PRODUCTO_NO_EDITABLE"
    bd.en_uso.clear()
    bd.productos[id_]["estado"] = "A"
    r = admin.patch(f"{BASE}/{id_}", json={"codigoProducto": "AHO004"})
    assert r.status_code == 409 and r.json()["code"] == "PRODUCTO_NO_EDITABLE"
    assert admin.patch(
        f"{BASE}/{id_}", json={"tipoProducto": "Credito"}
    ).status_code in (400, 422)


def test_elegibilidad_por_edad(bd, admin):
    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    url = f"{BASE}/{id_}/subproductos"
    r = admin.post(
        url,
        json={
            "codigoSubProducto": "AHO002-MN",
            "nombreSubProducto": "Menores",
            "edadMinima": 18,
            "edadMaxima": 17,
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "ELEGIBILIDAD_INVALIDA"
    r = admin.post(
        url,
        json={
            "codigoSubProducto": "AHO002-MN",
            "nombreSubProducto": "Menores",
            "edadMaxima": 17,
        },
    )
    assert r.status_code == 201 and r.json()["edadMaxima"] == 17
    sub = r.json()["idSubProducto"]
    r = admin.patch(f"{BASE}/subproductos/{sub}", json={"edadMinima": 20})
    assert r.status_code == 422 and r.json()["code"] == "ELEGIBILIDAD_INVALIDA"
    r = admin.patch(f"{BASE}/subproductos/{sub}", json={"edadMaxima": None})
    assert r.status_code == 200 and r.json()["edadMaxima"] is None


def test_eliminar_solo_en_borrador_sin_uso(bd, admin, asesor):
    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    assert asesor.delete(f"{BASE}/{id_}").status_code == 403
    bd.en_uso.add(id_)
    r = admin.delete(f"{BASE}/{id_}")
    assert r.status_code == 409 and r.json()["code"] == "PRODUCTO_EN_USO"
    bd.en_uso.clear()
    bd.productos[id_]["estado"] = "A"
    r = admin.delete(f"{BASE}/{id_}")
    assert r.status_code == 409 and r.json()["code"] == "PRODUCTO_ACTIVO"
    bd.productos[id_]["estado"] = "I"
    assert admin.delete(f"{BASE}/{id_}").status_code == 204
    assert id_ not in bd.productos
    assert admin.delete(f"{BASE}/{id_}").status_code == 404


def test_tipos_de_producto_vienen_con_el_software(bd, asesor):
    r = asesor.get(f"{BASE}/tipos")
    assert [t["codigo"] for t in r.json()] == ["CUENTA_AHORRO", "CREDITO", "TARJETA"]


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
    assert (
        admin.patch(
            f"{BASE}/subproductos/{sub['idSubProducto']}", json={"estado": "A"}
        ).status_code
        == 200
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


def _sub_de_credito(admin: TestClient) -> int:
    id_ = admin.post(
        BASE,
        json={
            "codigoProducto": "CRE009",
            "nombreProducto": "Crédito de consumo",
            "tipoProducto": "Credito",
            "idTipoCredito": 1,
        },
    ).json()["idProducto"]
    return admin.post(
        f"{BASE}/{id_}/subproductos",
        json={
            "codigoSubProducto": "CRE009-01",
            "nombreSubProducto": "Consumo hasta 10000",
        },
    ).json()["idSubProducto"]


# ---------- Cupos por canal y restricciones (cuentas y tarjetas) ----------

VENTANILLA = {
    "idCanal": 1,
    "cupoDiarioMaximo": 10000,
    "cupoMensualMaximo": 50000,
    "montoMaxTransaccion": 5000,
    "maxTransaccionesDia": 10,
}


@pytest.fixture
def cupos(bd: BdFalsa, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    estado: dict[str, Any] = {"cupos": {}, "personalizados": {}, "restricciones": {}}

    def listar(_c: Any, _id: int) -> list[dict[str, Any]]:
        return [
            {
                "id_canal": i,
                "codigo_canal": codigo,
                "nombre_canal": codigo.title(),
                "habilitado": i in estado["cupos"],
                **estado["cupos"].get(i, {}),
            }
            for i, codigo in ((1, "VENT"), (2, "ATM"))
        ]

    def guardar(_c: Any, _id: int, lista: list[dict[str, Any]]) -> None:
        estado["cupos"] = {
            c["id_canal"]: {k: v for k, v in c.items() if k != "id_canal"}
            for c in lista
        }

    def guardar_restriccion(
        _c: Any, _id: int, tipo: str, dias: Any, monto: Any, _d: str, _u: int
    ) -> None:
        estado["restricciones"][tipo] = dias if tipo == "SIN_RETIROS" else monto

    monkeypatch.setattr(repo, "listar_cupos", listar)
    monkeypatch.setattr(repo, "guardar_cupos", guardar)
    monkeypatch.setattr(repo, "canales_activos", lambda _c: {1, 2})
    monkeypatch.setattr(
        repo, "cupos_personalizados_maximos", lambda _c, _i: estado["personalizados"]
    )
    monkeypatch.setattr(repo, "guardar_restriccion", guardar_restriccion)
    monkeypatch.setattr(
        repo,
        "obtener_restricciones",
        lambda _c, _i: {
            "dias_sin_retiros": estado["restricciones"].get("SIN_RETIROS"),
            "saldo_minimo": estado["restricciones"].get("SALDO_MINIMO"),
        },
    )
    return estado


def _sub_de_cuenta(admin: TestClient) -> int:
    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    return admin.post(
        f"{BASE}/{id_}/subproductos",
        json={"codigoSubProducto": "AHO002-PN", "nombreSubProducto": "Natural"},
    ).json()["idSubProducto"]


def test_admin_habilita_canales_y_asesor_consulta(bd, cupos, admin, asesor):
    sub = _sub_de_cuenta(admin)
    url = f"{BASE}/subproductos/{sub}/cupos"
    assert asesor.put(url, json={"cupos": [VENTANILLA]}).status_code == 403
    r = admin.put(url, json={"cupos": [VENTANILLA]})
    assert r.status_code == 200, r.text
    por_canal = {c["codigoCanal"]: c for c in r.json()}
    assert (
        por_canal["VENT"]["habilitado"]
        and por_canal["VENT"]["cupoDiarioMaximo"] == 10000
    )
    assert not por_canal["ATM"]["habilitado"]
    assert asesor.get(url).status_code == 200


@pytest.mark.parametrize(
    ("cambio", "status"),
    [
        ({"cupoMensualMaximo": 100}, 422),  # mensual menor que el diario
        ({"montoMaxTransaccion": 20000}, 422),  # supera el diario
        ({"maxTransaccionesDia": 0}, 400),
        ({"idCanal": 9}, 422),  # canal inexistente
    ],
)
def test_cupos_invalidos(bd, cupos, admin, cambio, status):
    sub = _sub_de_cuenta(admin)
    r = admin.put(
        f"{BASE}/subproductos/{sub}/cupos", json={"cupos": [{**VENTANILLA, **cambio}]}
    )
    assert r.status_code in (status, 422), r.text
    assert cupos["cupos"] == {}


def test_no_baja_el_maximo_bajo_un_cupo_personalizado(bd, cupos, admin):
    sub = _sub_de_cuenta(admin)
    cupos["personalizados"] = {
        1: {"cupo_diario": 8000, "cupo_mensual": 9000, "monto_max_transaccion": 100}
    }
    url = f"{BASE}/subproductos/{sub}/cupos"
    r = admin.put(
        url,
        json={
            "cupos": [
                {**VENTANILLA, "cupoDiarioMaximo": 6000, "montoMaxTransaccion": 1000}
            ]
        },
    )
    assert r.status_code == 409 and r.json()["code"] == "CUPO_MENOR_QUE_PERSONALIZADO"
    assert admin.put(url, json={"cupos": []}).status_code == 409  # quitar el canal
    assert admin.put(url, json={"cupos": [VENTANILLA]}).status_code == 200


def test_cupos_no_aplican_a_creditos(bd, cupos, admin):
    sub = _sub_de_credito(admin)
    r = admin.get(f"{BASE}/subproductos/{sub}/cupos")
    assert r.status_code == 422 and r.json()["code"] == "CAMPO_NO_APLICA"


def test_restricciones_de_cuenta(bd, cupos, admin, asesor):
    sub = _sub_de_cuenta(admin)
    url = f"{BASE}/subproductos/{sub}/restricciones"
    r = admin.put(url, json={"diasSinRetiros": 30, "saldoMinimo": 100})
    assert r.status_code == 200 and r.json() == {
        "diasSinRetiros": 30,
        "saldoMinimo": 100,
    }
    r = admin.put(url, json={"diasSinRetiros": None, "saldoMinimo": 100})
    assert r.json()["diasSinRetiros"] is None
    assert asesor.put(url, json={}).status_code == 403
    assert admin.put(url, json={"saldoMinimo": 0}).status_code in (400, 422)


@pytest.mark.parametrize("estado", ["Activo", "Suspendido", "Retirado"])
@pytest.mark.parametrize(
    "campo,valor",
    [
        ("codigoProducto", "AHO009"),
        ("nombreProducto", "Nombre nuevo"),
        ("descripcion", "Otra descripcion"),
        ("montoAperturaMinimo", 5),
        ("permiteOperacionesPresenciales", False),
    ],
)
def test_datos_dejan_de_ser_editables_tras_activar(bd, admin, estado, campo, valor):
    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    bd.productos[id_]["estado_catalogo"] = estado
    r = admin.patch(f"{BASE}/{id_}", json={campo: valor})
    assert r.status_code == 409 and r.json()["code"] == "PRODUCTO_NO_EDITABLE"


def test_no_se_elimina_suspendido_ni_se_regresa_a_borrador(bd, admin):
    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    bd.productos[id_]["estado_catalogo"] = "Suspendido"
    assert admin.delete(f"{BASE}/{id_}").status_code == 409
    r = admin.patch(f"{BASE}/{id_}", json={"estadoCatalogo": "Borrador"})
    assert r.status_code == 409 and r.json()["code"] == "ESTADO_INVALIDO"


def test_subproducto_nace_borrador_y_guarda_elegibilidad(bd, admin):
    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    sub = admin.post(
        f"{BASE}/{id_}/subproductos",
        json={
            "codigoSubProducto": "AHO-MN",
            "nombreSubProducto": "Menores",
            "edadMinima": 0,
            "edadMaxima": 17,
            "tipoClientePermitido": "Natural",
            "requiereTutor": True,
            "maximoPorCliente": 1,
        },
    ).json()
    assert sub["estadoCatalogo"] == "Borrador" and sub["estado"] == "I"
    assert sub["requiereTutor"] and sub["maximoPorCliente"] == 1
    url = f"{BASE}/subproductos/{sub['idSubProducto']}"
    assert admin.patch(url, json={"estadoCatalogo": "Activo"}).status_code == 200
    r = admin.patch(url, json={"edadMaxima": 18})
    assert r.status_code == 409 and r.json()["code"] == "PRODUCTO_NO_EDITABLE"


def test_tipos_sin_ruta_de_alta(bd, admin):
    assert admin.post(f"{BASE}/tipos", json={"codigo": "NUEVO"}).status_code == 405


def test_estado_inconsistente_no_se_guarda(bd, admin):
    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    r = admin.patch(f"{BASE}/{id_}", json={"estado": "I", "estadoCatalogo": "Activo"})
    assert r.status_code == 422 and r.json()["code"] == "ESTADO_INVALIDO"


def test_consultar_lo_decide_prd_consultar_no_el_rol(bd):
    # ADMIN sin prd-consultar no consulta; CAJERO con prd-consultar sí
    from dataclasses import replace

    from app.core.security.auth import usuario_actual

    client = _cliente("ADMIN")
    overrides = cast(FastAPI, client.app).dependency_overrides
    overrides[usuario_actual] = lambda: replace(usuario_con_roles("ADMIN"), permisos=())
    assert client.get(BASE).status_code == 403
    overrides[usuario_actual] = lambda: replace(
        usuario_con_roles("CAJERO"), permisos=("prd-consultar",)
    )
    assert client.get(BASE).status_code == 200
    assert client.get(BASE + "/tipos").status_code == 200


@pytest.mark.parametrize(
    "metodo,path,body",
    [
        ("post", "", AHORRO),
        ("patch", "/1", {"nombreProducto": "Nuevo nombre"}),
        ("get", "/subproductos/1/ficha/imprimible", None),
    ],
)
def test_permiso_workos_exigido_aunque_sea_admin(bd, metodo, path, body):
    from dataclasses import replace

    from app.core.security.auth import usuario_actual

    client = _cliente("ADMIN")
    cast(FastAPI, client.app).dependency_overrides[usuario_actual] = lambda: replace(
        usuario_con_roles("ADMIN"), permisos=()
    )
    r = client.request(metodo, BASE + path, json=body)
    assert r.status_code == 403 and r.json()["code"] == "SIN_PERMISO"


def test_historial_central_conserva_antes_y_despues_sin_truncar(bd, admin, eventos):
    import json

    id_ = admin.post(BASE, json=AHORRO).json()["idProducto"]
    antes = dict(bd.productos[id_])
    descripcion = "Descripcion de producto " * 10
    r = admin.patch(f"{BASE}/{id_}", json={"descripcion": descripcion})
    assert r.status_code == 200
    partes = [e for e in eventos if e.accion == "PRD_PRODUCTO_EDITADO"]
    assert len(partes) > 1 and all(len(e.descripcion) <= 500 for e in partes)
    reconstruido = json.loads(
        "".join(e.descripcion.split(" datos=", 1)[1] for e in partes)
    )
    assert reconstruido["antes"]["descripcion"] == antes["descripcion"]
    assert reconstruido["despues"]["descripcion"] == descripcion.strip()
    assert all(e.id_registro == str(id_) and "ADMIN" in (e.roles or "") for e in partes)


def test_sql_elegibilidad_conserva_aliases_y_estados_del_producto(monkeypatch):
    consultas = []

    def rows(conn, sql, params=None):
        consultas.append(sql)
        return []

    monkeypatch.setattr(repo, "_rows", rows)
    assert repo.datos_elegibilidad(MagicMock(), 1, 2) is None
    sql = consultas[0]
    assert "p.Estado AS estado_producto" in sql
    assert "p.EstadoProducto AS estado_producto_nuevo" in sql
    assert "p.EstadoSubProducto" not in sql

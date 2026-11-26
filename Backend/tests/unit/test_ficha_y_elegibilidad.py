"""Ficha del subproducto y productos elegibles para un cliente (E3-02 #375), sin BD."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.modules.catalogos import repository as catalogos_repo
from app.modules.catalogos import router as catalogos_api
from app.modules.catalogos import service as catalogos_service
from app.modules.catalogos.router import router as catalogos_router
from app.modules.clientes.habilitacion import HabilitacionCliente
from app.modules.contabilidad import cuentas_producto
from app.modules.cuentas import service as cuentas_service
from app.modules.cuentas.router import router as cuentas_router
from app.modules.productos import activacion, vinculos
from app.modules.productos import repository as repo
from app.modules.productos import service as productos_service
from app.modules.productos.router import router as productos_router
from tests.sesion import simular_sesion, usuario_con_roles

PRODUCTO = {
    "id_producto": 1,
    "codigo_producto": "TAR001",
    "nombre_producto": "Tarjeta Mastercard",
    "descripcion": None,
    "tipo_producto": "Tarjeta",
    "tipo_cuenta": None,
    "monto_apertura_minimo": None,
    "id_tipo_credito": None,
    "nombre_tipo_credito": None,
    "id_red": 2,
    "nombre_red": "Mastercard",
    "permite_operaciones_presenciales": True,
    "estado": "A",
}
SUB = {
    "id_sub_producto": 10,
    "id_producto": 1,
    "codigo_sub_producto": "TCR001-MC",
    "nombre_sub_producto": "Crédito clásica",
    "estado": "A",
    "fecha_registro": datetime(2026, 11, 15),
    "edad_minima": 18,
    "edad_maxima": None,
}


def _cliente(router: Any) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[cooperativa] = lambda: MagicMock()
    simular_sesion(app, usuario_con_roles("ASESOR"))
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def ficha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo, "condiciones_vigentes", lambda *a: None)
    vacio = {
        "tasas_interes": [],
        "comisiones": [],
        "seguros": [],
        "sistemas_amortizacion": [],
    }
    del_producto = {
        **vacio,
        "tasas_interes": [4],
        "comisiones": [{"id_comision": 1, "exonerado": False}],
    }
    propios = {
        **vacio,
        "comisiones": [
            {"id_comision": 1, "exonerado": True},
            {"id_comision": 2, "exonerado": False},
        ],
    }
    monkeypatch.setattr(
        repo, "obtener_subproducto", lambda _c, i, **_k: SUB if i == 10 else None
    )
    monkeypatch.setattr(repo, "obtener_producto", lambda _c, i, **_k: PRODUCTO)
    monkeypatch.setattr(repo, "listar_subproductos", lambda _c, _i=None: [SUB])
    monkeypatch.setattr(
        vinculos, "leer", lambda _c, d, _i: del_producto if d == "producto" else propios
    )
    monkeypatch.setattr(catalogos_service, "hoy", lambda: date(2026, 11, 15))
    monkeypatch.setattr(
        catalogos_repo,
        "listar_tasas_interes",
        lambda _c, _h, *_a: [
            {
                "id_tasa_interes": 4,
                "tipo_tasa": "TARJETA_COMPRA",
                "tasa_nominal_anual": Decimal("0.25"),
                "monto_minimo": None,
                "monto_maximo": None,
                "plazo_maximo_meses": None,
                "vigente": True,
            },
            {
                "id_tasa_interes": 5,
                "tipo_tasa": "AHORRO",
                "tasa_nominal_anual": Decimal("0.03"),
                "monto_minimo": None,
                "monto_maximo": None,
                "plazo_maximo_meses": None,
                "vigente": True,
            },
        ],
    )
    comision = {"tipo_calculo": "Fijo", "valor": Decimal("0.50"), "nombre_canal": "POS"}
    monkeypatch.setattr(
        catalogos_repo,
        "listar_comisiones",
        lambda _c: [
            {
                **comision,
                "id_comision": 1,
                "codigo_comision": "GAS",
                "descripcion": "Recargo gasolineras",
            },
            {
                **comision,
                "id_comision": 2,
                "codigo_comision": "EXT",
                "descripcion": "Compra exterior",
            },
        ],
    )
    monkeypatch.setattr(catalogos_repo, "listar_seguros", lambda _c: [])
    monkeypatch.setattr(
        catalogos_repo,
        "reglas_edad",
        lambda _c, _i: {
            "subproducto": 18,
            "red": 21,
            "politica": None,
            "efectiva": 21,
            "maxima": None,
        },
    )
    monkeypatch.setattr(
        repo,
        "listar_cupos",
        lambda _c, _i: [
            {
                "id_canal": 1,
                "codigo_canal": "VENT",
                "nombre_canal": "Ventanilla",
                "habilitado": True,
                "cupo_diario_maximo": Decimal(500),
                "cupo_mensual_maximo": Decimal(5000),
                "monto_max_transaccion": Decimal(300),
                "max_transacciones_dia": 5,
            },
            {
                "id_canal": 2,
                "codigo_canal": "ATM",
                "nombre_canal": "Cajero",
                "habilitado": False,
            },
        ],
    )


def test_ficha_reune_lo_vigente_y_lo_heredado(ficha):
    r = _cliente(productos_router).get(
        "https://testserver/api/v1/productos/subproductos/10/ficha"
    )
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["subproducto"]["edadMinima"] == 18
    # Rige la más alta: la red pide 21
    assert (
        f["elegibilidad"]["edadMinima"] == 21
        and f["elegibilidad"]["edadMinimaRed"] == 21
    )
    assert [(t["idTasaInteres"], t["delProducto"]) for t in f["tasas"]] == [(4, True)]
    # GAS viene del producto pero el subproducto la exonera: no aparece
    assert [c["codigoComision"] for c in f["comisiones"]] == ["EXT"]
    assert [c["codigoCanal"] for c in f["cupos"]] == ["VENT"]
    assert f["restricciones"] is None  # solo cuentas
    assert (
        _cliente(productos_router)
        .get("https://testserver/api/v1/productos/subproductos/99/ficha")
        .status_code
        == 404
    )


@pytest.mark.parametrize(
    ("nacimiento", "edad"),
    [(date(2010, 6, 1), 16), (date(1990, 11, 16), 35), (None, -1)],
)
def test_productos_para_un_cliente_filtran_por_edad(monkeypatch, nacimiento, edad):
    recibido: dict[str, Any] = {}
    monkeypatch.setattr(catalogos_service, "hoy", lambda: date(2026, 11, 15))
    monkeypatch.setattr(
        catalogos_repo, "perfil_cliente", lambda _c, _i: ("Natural", nacimiento)
    )
    monkeypatch.setattr(
        catalogos_repo,
        "listar_productos",
        lambda _c, _t, _tt, e: recibido.setdefault("edad", e) and [],
    )
    r = _cliente(catalogos_router).get(
        "https://testserver/api/v1/catalogos/productos?idCliente=3"
    )
    assert r.status_code == 200 and recibido["edad"] == edad


def test_cliente_inexistente(monkeypatch):
    monkeypatch.setattr(catalogos_repo, "perfil_cliente", lambda _c, _i: None)
    r = _cliente(catalogos_router).get(
        "https://testserver/api/v1/catalogos/productos?idCliente=3"
    )
    assert r.status_code == 404 and r.json()["code"] == "CLIENTE_NO_ENCONTRADO"


def test_edad_cumplida():
    assert catalogos_service.edad_en(date(2008, 11, 16), date(2026, 11, 15)) == 17
    assert catalogos_service.edad_en(date(2008, 11, 15), date(2026, 11, 15)) == 18


def test_catalogo_exige_estados_activos_nuevos_y_legados(monkeypatch):
    consultas = []

    def filas(_conn, sql, _params=None):
        consultas.append(sql)
        return []

    monkeypatch.setattr(catalogos_repo, "_rows", filas)
    catalogos_repo.listar_productos(MagicMock(), None)
    assert "EstadoProducto = 'Activo'" in consultas[0]
    assert "s.EstadoSubProducto = 'Activo'" in consultas[1]
    assert "p.EstadoProducto = 'Activo'" in consultas[1]


def test_catalogo_reutiliza_elegibilidad_completa_y_descarta_vacios(monkeypatch):
    monkeypatch.setattr(
        catalogos_repo, "perfil_cliente", lambda *_a: ("Natural", date(2010, 1, 1))
    )
    monkeypatch.setattr(
        catalogos_repo,
        "listar_productos",
        lambda *_a: [
            {
                "id_producto": 1,
                "codigo_producto": "AHO001",
                "nombre_producto": "Ahorro",
                "tipo_producto": "Cuenta",
                "permite_operaciones_presenciales": True,
                "subproductos": [
                    {
                        "id_sub_producto": 1,
                        "codigo_sub_producto": "AHO-MN",
                        "nombre_sub_producto": "Menores",
                    },
                    {
                        "id_sub_producto": 2,
                        "codigo_sub_producto": "AHO-AD",
                        "nombre_sub_producto": "Adultos",
                    },
                ],
            },
            {"id_producto": 2, "subproductos": [{"id_sub_producto": 3}]},
        ],
    )
    llamados = []

    def elegible(conn, cliente, sub, fecha):
        llamados.append((cliente, sub, fecha))
        return sub == 1, [] if sub == 1 else ["NO_ELEGIBLE"]

    monkeypatch.setattr(productos_service, "cliente_elegible", elegible)
    r = _cliente(catalogos_router).get(
        "https://testserver/api/v1/catalogos/productos?idCliente=3"
    )
    assert r.status_code == 200, r.text
    assert [[s["idSubProducto"] for s in p["subproductos"]] for p in r.json()] == [[1]]
    assert [c[1] for c in llamados] == [1, 2, 3]


@pytest.mark.parametrize("legado_pj", [False, True])
@pytest.mark.parametrize(
    ("tipo", "nacimiento", "rol", "cuenta", "ajustado", "esperados"),
    [
        ("Natural", date(1988, 6, 1), None, None, True, ["AHO001-PN", "AHO001-ALT"]),
        ("Juridico", date(2015, 6, 1), "RepresentanteLegal", None, True, ["AHO001-PJ"]),
        ("Natural", date(2011, 6, 1), "Tutor", None, True, ["AHO001-MN"]),
        ("Juridico", None, None, None, True, []),
        ("Natural", date(2011, 6, 1), None, None, True, []),
        ("Natural", date(2011, 6, 1), "Tutor", None, False, []),
        ("Natural", date(1988, 6, 1), None, "PendienteDeposito", True, ["AHO001-ALT"]),
        (
            "Natural",
            date(1988, 6, 1),
            None,
            "Anulada",
            True,
            ["AHO001-PN", "AHO001-ALT"],
        ),
    ],
)
def test_e601_catalogo_de_apertura(
    monkeypatch, tipo, nacimiento, rol, cuenta, ajustado, esperados, legado_pj
):
    fecha = date(2026, 11, 25)
    reglas = {
        1: ("AHO001-PN", "Natural", 18, None, False, ajustado),
        2: (
            "AHO001-PJ",
            "Ambos" if legado_pj else "Juridico",
            18 if legado_pj else None,
            None,
            False,
            True,
        ),
        7: (
            "AHO001-MN",
            "Natural",
            0 if ajustado else None,
            17 if ajustado else None,
            rol == "Tutor",
            ajustado,
        ),
        10: ("AHO001-ALT", "Natural", 18, None, False, ajustado),
        11: ("AHO001-SIN-CONDICIONES", "Ambos", None, None, False, ajustado),
    }

    def datos(_conn, _id_cliente, id_sub):
        codigo, permitido, minima, maxima, tutor, activo = reglas[id_sub]
        return {
            "tipo_cliente": tipo,
            "fecha_nacimiento": nacimiento,
            "estado_cliente": "Activo",
            "codigo_sub_producto": codigo,
            "tipo_permitido": permitido,
            "edad_minima": minima,
            "edad_maxima": maxima,
            "requiere_tutor": tutor,
            "estado_producto": "A",
            "estado_producto_nuevo": "Activo",
            "estado_subproducto": "A" if activo else "I",
            "estado_subproducto_nuevo": "Activo" if activo else "Suspendido",
            "tipo_producto": "Cuenta",
            "id_requerido": None,
            "maximo_por_cliente": 2 if id_sub == 1 else None,
        }

    def relacion(_conn, _id_cliente, requerido, _fecha):
        return {"IdRelacion": 1} if rol == requerido else None

    monkeypatch.setattr(catalogos_service, "hoy", lambda: fecha)
    monkeypatch.setattr(cuentas_service, "edad_mayoria", lambda *_a: 18)
    monkeypatch.setattr(catalogos_api, "relacion_vigente", relacion)
    monkeypatch.setattr(productos_service, "relacion_vigente", relacion)
    monkeypatch.setattr(
        catalogos_repo, "perfil_cliente", lambda *_a: (tipo, nacimiento)
    )
    monkeypatch.setattr(
        catalogos_repo,
        "listar_productos",
        lambda _conn, _tipo, _tarjeta, edad: [
            {
                "id_producto": 1,
                "codigo_producto": "AHO001",
                "nombre_producto": "Ahorro",
                "tipo_producto": "Cuenta",
                "permite_operaciones_presenciales": True,
                "subproductos": [
                    {
                        "id_sub_producto": id_sub,
                        "codigo_sub_producto": regla[0],
                        "nombre_sub_producto": regla[0],
                    }
                    for id_sub, regla in reglas.items()
                    if edad is None
                    or (
                        (regla[2] is None or edad >= regla[2])
                        and (regla[3] is None or edad <= regla[3])
                    )
                ],
            }
        ],
    )
    monkeypatch.setattr(repo, "datos_elegibilidad", datos)
    monkeypatch.setattr(
        repo,
        "cuentas_cliente_para_elegibilidad",
        lambda *_a: [{"id_subproducto": 1, "estado": cuenta}] if cuenta else [],
    )
    monkeypatch.setattr(repo, "tarjetas_cliente_para_elegibilidad", lambda *_a: [])
    monkeypatch.setattr(
        repo,
        "restricciones_vigentes",
        lambda _conn, id_sub, *_a: (
            [{"tipo_restriccion": "MAXIMO_CUENTAS_CLIENTE", "cantidad": 1}]
            if id_sub == 1
            else []
        ),
    )
    monkeypatch.setattr(
        repo,
        "condiciones_vigentes",
        lambda _conn, id_sub, *_a: (
            {"monto_apertura_minimo": 20} if id_sub != 11 else None
        ),
    )

    respuesta = _cliente(catalogos_router).get(
        "https://testserver/api/v1/catalogos/productos?tipo=Cuenta&idCliente=3"
    )
    assert respuesta.status_code == 200, respuesta.text
    assert [
        s["codigoSubProducto"] for p in respuesta.json() for s in p["subproductos"]
    ] == esperados


def test_e601_rechaza_apertura_de_ahorro_juridico_para_persona_natural(monkeypatch):
    monkeypatch.setattr(
        cuentas_service.clientes_repository, "bloquear_cliente", lambda *_a: {}
    )
    monkeypatch.setattr(
        cuentas_service,
        "cliente_habilitado",
        lambda *_a: HabilitacionCliente(habilitado=True, motivos=[]),
    )
    monkeypatch.setattr(
        cuentas_service.repository,
        "obtener_subproducto",
        lambda *_a: {"tipo_producto": "Cuenta"},
    )
    monkeypatch.setattr(
        repo,
        "datos_elegibilidad",
        lambda *_a: {
            "tipo_cliente": "Natural",
            "fecha_nacimiento": date(1988, 6, 1),
            "estado_cliente": "Activo",
            "codigo_sub_producto": "AHO001-PJ",
            "tipo_permitido": "Ambos",
            "edad_minima": 18,
            "edad_maxima": None,
            "requiere_tutor": False,
            "estado_producto": "A",
            "estado_producto_nuevo": "Activo",
            "estado_subproducto": "A",
            "estado_subproducto_nuevo": "Activo",
            "tipo_producto": "Cuenta",
            "id_requerido": None,
            "maximo_por_cliente": None,
        },
    )
    monkeypatch.setattr(repo, "cuentas_cliente_para_elegibilidad", lambda *_a: [])
    monkeypatch.setattr(repo, "tarjetas_cliente_para_elegibilidad", lambda *_a: [])
    monkeypatch.setattr(repo, "restricciones_vigentes", lambda *_a: [])
    registrar = MagicMock()
    monkeypatch.setattr(cuentas_service.repository, "registrar_apertura", registrar)

    respuesta = _cliente(cuentas_router).post(
        "https://testserver/api/v1/cuentas", json={"idCliente": 1, "idSubProducto": 2}
    )

    assert respuesta.status_code == 422, respuesta.text
    assert respuesta.json()["code"] == "SUBPRODUCTO_NO_ELEGIBLE"
    assert respuesta.json()["bloqueos"] == ["TIPO_CLIENTE_NO_PERMITIDO"]
    registrar.assert_not_called()


@pytest.mark.parametrize("catalogo_activo", [True, False])
def test_e601_activacion_permite_exigir_tutor_verificable(monkeypatch, catalogo_activo):
    monkeypatch.setattr(
        activacion,
        "_sub",
        lambda *_a: {
            "EdadMinima": 0,
            "EdadMaxima": 17,
            "RequiereTutor": True,
            "EstadoProducto": "Activo",
            "CodigoTipo": "CUENTA_AHORRO",
            "GeneraNumeroCuenta": True,
        },
    )
    monkeypatch.setattr(
        activacion,
        "_existe",
        lambda _conn, sql, **_p: (
            catalogo_activo if "TipoRelacionCliente" in sql else True
        ),
    )
    monkeypatch.setattr(cuentas_producto, "roles_faltantes", lambda *_a: [])
    monkeypatch.setattr(
        activacion, "_plantillas", lambda *_a: ("PLANTILLAS", None, None)
    )
    puntos = activacion.lista(MagicMock(), 7, date(2026, 11, 25))
    elegibilidad = next(p for p in puntos if p["codigo"] == "ELEGIBILIDAD")
    assert elegibilidad["cumple"] is catalogo_activo


def test_ficha_incluye_condiciones_vigentes_y_no_tasas_futuras(ficha, monkeypatch):
    originales = catalogos_repo.listar_tasas_interes(MagicMock(), date(2026, 11, 15))
    monkeypatch.setattr(
        catalogos_repo,
        "listar_tasas_interes",
        lambda *_a: [*originales, {**originales[0], "vigente": False}],
    )
    monkeypatch.setattr(
        repo,
        "condiciones_vigentes",
        lambda *_a: {
            "monto_apertura_minimo": 10,
            "saldo_minimo": 5,
            "tasa_interes_anual": 0,
            "costo_mantenimiento": 0,
            "vigencia_desde": date(2026, 1, 1),
        },
    )
    r = _cliente(productos_router).get(
        "https://testserver/api/v1/productos/subproductos/10/ficha"
    )
    assert r.status_code == 200, r.text
    assert r.json()["condiciones"]["montoAperturaMinimo"] == 10
    assert r.json()["condiciones"]["tasaInteresAnual"] == 0
    assert all(t["vigente"] for t in r.json()["tasas"])

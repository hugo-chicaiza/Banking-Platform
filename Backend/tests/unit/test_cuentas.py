import asyncio
import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast, get_args

import httpx
import pytest
from fastapi import HTTPException
from fastapi.dependencies.utils import request_params_to_args
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError
from starlette.datastructures import QueryParams
from starlette.requests import Request

from app.core.api.errors import ProblemDetailsRoute
from app.core.security.auth import Usuario, require_auth
from app.main import app
from app.modules.cuentas import repository, router, service
from app.modules.cuentas.schemas import (
    ID_MONEDA_USD,
    Cuenta,
    CuentaCreate,
    CuentaEstadoUpdate,
    CupoUpdate,
    EstadoCuenta,
    SaldoCuenta,
)
from app.modules.cuentas.service import actualizar_cupo as _actualizar_cupo_servicio


class _Result:
    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self.filas = filas

    def mappings(self) -> list[dict[str, Any]]:
        return self.filas

    def scalar_one(self) -> Any:
        fila = self.filas[0]
        return next(iter(fila.values()))


class _FakeConn:
    def __init__(self, respuestas: tuple[list[dict[str, Any]], ...] = ()) -> None:
        self.respuestas = list(respuestas)
        self.consultas: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql: Any, params: dict[str, Any]) -> _Result:
        self.consultas.append((str(sql), params))
        return _Result(self.respuestas.pop(0))

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _fake_conn(*respuestas: list[dict[str, Any]]) -> _FakeConn:
    return _FakeConn(respuestas)


def _cuenta_row(**overrides: Any) -> dict[str, Any]:
    """Fila enriquecida para validar el contrato una vez resuelta la moneda."""
    return {
        "id_cuenta": 501,
        "numero_cuenta": "AH00000001",
        "id_cliente": 125,
        "id_producto": 2,
        "id_agencia": "001",
        "tipo_cuenta": "Ahorro",
        "id_moneda": ID_MONEDA_USD,
        "saldo": Decimal("0.00"),
        "saldo_retenido": Decimal("0.00"),
        "estado": "ACTIVA",
        **overrides,
    }


def _cuenta_bd_row(**overrides: Any) -> dict[str, Any]:
    """Proyección real de A-02: tipo vía Producto, estado de BD y sin moneda."""
    fila = _cuenta_row(**{"estado": "Activa", **overrides})
    fila.pop("id_moneda")
    return fila


def _assert_http_error(
    exc: pytest.ExceptionInfo[HTTPException], status: int, code: str
) -> None:
    assert exc.value.status_code == status
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("code") == code


def _assert_solo_lectura(db: _FakeConn) -> None:
    assert not db.respuestas
    assert (db.commits, db.rollbacks) == (0, 0)
    assert all(
        palabra not in sql.upper()
        for sql, _ in db.consultas
        for palabra in ("INSERT ", "UPDATE ", "DELETE ", "EXEC ", "MERGE ")
    )
    assert all("Cuentas.Cuenta" in sql for sql, _ in db.consultas)
    assert all(
        "INNER JOIN ProductosFinancieros.Producto AS p" in sql
        and "ON p.IdProducto = c.IdProducto" in sql
        and "p.TipoCuenta AS tipo_cuenta" in sql
        and "c.TipoCuenta" not in sql
        and "IdMoneda" not in sql
        for sql, _ in db.consultas
    )
    assert all(
        tabla not in sql
        for sql, _ in db.consultas
        for tabla in ("Clientes.", "Tarjeta.", "Credito.")
    )


_CLIENTE_ACTIVO = {"estado": "Activo"}
_RIESGO_APROBADO = {"estado": "Aprobado"}
_SUBPRODUCTO_CUENTA = {
    "id_subproducto": 20,
    "id_producto": 2,
    "tipo_producto": "Cuenta",
    "tipo_cuenta": "Ahorro",
    "estado_producto": "A",
    "estado_subproducto": "A",
    "monto_apertura_minimo": Decimal("50.00"),
}
_AGENCIA_ACTIVA = {"estado": "A"}
_PAYLOAD = {
    "idCliente": 125,
    "idSubProducto": 20,
    "idAgencia": "001",
    "montoInicial": "50.00",
    "idMoneda": ID_MONEDA_USD,
}


def _patch_repo(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cliente: Any = None,
    riesgo: Any = None,
    subproducto: Any = None,
    agencia: Any = None,
    cuenta: Any = None,
) -> None:
    monkeypatch.setattr(repository, "obtener_cliente", lambda conn, _id: cliente)
    monkeypatch.setattr(repository, "obtener_riesgo_vigente", lambda conn, _id: riesgo)
    monkeypatch.setattr(
        repository, "obtener_subproducto", lambda conn, _id: subproducto
    )
    monkeypatch.setattr(repository, "obtener_agencia", lambda conn, _id: agencia)
    monkeypatch.setattr(repository, "abrir_cuenta", lambda *args, **kw: cuenta)


def _abrir_cuenta(db: _FakeConn | None = None) -> Cuenta:
    return service.abrir_cuenta(
        cast(Connection, db or _fake_conn()), CuentaCreate(**_PAYLOAD), 12
    )


# CTA-01: se conservan los casos existentes invocando directamente el servicio.


def test_abrir_cuenta_201(monkeypatch: pytest.MonkeyPatch):
    llamada: dict[str, Any] = {}
    _patch_repo(
        monkeypatch,
        cliente=_CLIENTE_ACTIVO,
        riesgo=_RIESGO_APROBADO,
        subproducto=_SUBPRODUCTO_CUENTA,
        agencia=_AGENCIA_ACTIVA,
        cuenta=_cuenta_row(),
    )

    def abrir(*args, **kwargs):
        llamada.update(kwargs)
        # El servicio aplica la regla global aunque una fuente antigua traiga otro dato.
        return _cuenta_row(id_moneda=978)

    monkeypatch.setattr(repository, "abrir_cuenta", abrir)
    monkeypatch.setattr(
        service, "_generar_numero_cuenta", lambda conn, tipo: "AH00000001"
    )
    db = _fake_conn()
    body = _abrir_cuenta(db).model_dump(mode="json", by_alias=True)
    assert body["idCuenta"] == 501
    assert body["numeroCuenta"] == "AH00000001"
    assert body["estado"] == "ACTIVA"
    assert body["saldo"] == 0.0
    assert body["saldoRetenido"] == 0.0
    assert body["idMoneda"] == ID_MONEDA_USD
    assert llamada["id_subproducto"] == 20
    assert llamada["monto_inicial"] == Decimal("50.00")
    assert llamada["creado_por"] == 12
    assert "id_moneda" not in llamada
    assert (db.commits, db.rollbacks) == (1, 0)


@pytest.mark.parametrize(
    ("tipo_cuenta", "ultimo", "esperado"),
    [("Ahorro", 9, "AH00000010"), ("Corriente", 0, "CC00000001")],
)
def test_generar_numero_cuenta_bloquea_rango_y_omite_sufijos_no_numericos(
    tipo_cuenta, ultimo, esperado
):
    db = _fake_conn([{"ultimo": ultimo}])
    assert service._generar_numero_cuenta(cast(Connection, db), tipo_cuenta) == esperado
    sql, params = db.consultas[0]
    assert "WITH (UPDLOCK, HOLDLOCK)" in sql
    assert "TRY_CONVERT" in sql
    assert params == {"patron": esperado[:2] + "%"}


def test_repositorio_apertura_usa_firma_real_y_lee_por_id():
    db = _fake_conn([{"id_cuenta": 501}], [_cuenta_bd_row()])
    cuenta = repository.abrir_cuenta(
        cast(Connection, db),
        numero_cuenta="AH00000001",
        id_cliente=125,
        id_subproducto=20,
        id_agencia="001",
        monto_inicial=Decimal("50.00"),
        creado_por=12,
    )
    assert cuenta["id_cuenta"] == 501
    sql, params = db.consultas[0]
    for parametro in (
        "@IdCliente",
        "@IdSubProducto",
        "@IdAgencia",
        "@NumeroCuenta",
        "@MontoInicial",
        "@CreadoPor",
        "@IdCuenta",
    ):
        assert parametro in sql
    for obsoleto in ("@IdProducto", "@TipoCuenta", "@IdMoneda"):
        assert obsoleto not in sql
    assert params == {
        "id_cliente": 125,
        "id_subproducto": 20,
        "id_agencia": "001",
        "numero_cuenta": "AH00000001",
        "monto_inicial": Decimal("50.00"),
        "creado_por": 12,
    }
    assert db.consultas[1][1] == {"id_cuenta": 501}


def test_cliente_no_existe_409(monkeypatch: pytest.MonkeyPatch):
    _patch_repo(monkeypatch, cliente=None)
    with pytest.raises(HTTPException) as exc:
        _abrir_cuenta()
    _assert_http_error(exc, 409, "CLIENTE_NO_ACTIVO")


@pytest.mark.parametrize("estado", ["Pendiente", "Bloqueado", "Inactivo", "Cerrado"])
def test_cliente_no_activo_409(monkeypatch: pytest.MonkeyPatch, estado):
    _patch_repo(monkeypatch, cliente={"estado": estado})
    with pytest.raises(HTTPException) as exc:
        _abrir_cuenta()
    _assert_http_error(exc, 409, "CLIENTE_NO_ACTIVO")


def test_riesgo_rechazado_409(monkeypatch: pytest.MonkeyPatch):
    _patch_repo(monkeypatch, cliente=_CLIENTE_ACTIVO, riesgo={"estado": "Rechazado"})
    with pytest.raises(HTTPException) as exc:
        _abrir_cuenta()
    _assert_http_error(exc, 409, "RIESGO_RECHAZADO")


def test_repositorio_riesgo_usa_columnas_reales_y_parametro_ligado():
    db = _fake_conn([{"estado": "Aprobado"}])
    resultado = repository.obtener_riesgo_vigente(cast(Connection, db), 125)
    assert resultado == {"estado": "Aprobado"}
    sql, params = db.consultas[0]
    assert "ResultadoEvaluacion AS estado" in sql
    assert "EsVigente = 1" in sql
    assert "Estado AS estado" not in sql
    assert params == {"id_cliente": 125}


@pytest.mark.parametrize(
    "subproducto",
    [
        None,
        {**_SUBPRODUCTO_CUENTA, "tipo_producto": "Tarjeta"},
        {**_SUBPRODUCTO_CUENTA, "estado_producto": "I"},
        {**_SUBPRODUCTO_CUENTA, "estado_subproducto": "I"},
    ],
    ids=["inexistente", "tipo_incorrecto", "producto_inactivo", "subproducto_inactivo"],
)
def test_producto_invalido_422(monkeypatch: pytest.MonkeyPatch, subproducto):
    _patch_repo(
        monkeypatch,
        cliente=_CLIENTE_ACTIVO,
        riesgo=_RIESGO_APROBADO,
        subproducto=subproducto,
    )
    with pytest.raises(HTTPException) as exc:
        _abrir_cuenta()
    _assert_http_error(exc, 422, "PRODUCTO_NO_ES_CUENTA")


def test_monto_inicial_inferior_al_minimo_422(monkeypatch: pytest.MonkeyPatch):
    _patch_repo(
        monkeypatch,
        cliente=_CLIENTE_ACTIVO,
        riesgo=_RIESGO_APROBADO,
        subproducto=_SUBPRODUCTO_CUENTA,
    )
    payload = CuentaCreate(**{**_PAYLOAD, "montoInicial": "49.99"})
    with pytest.raises(HTTPException) as exc:
        service.abrir_cuenta(cast(Connection, _fake_conn()), payload, 12)
    _assert_http_error(exc, 422, "MONTO_APERTURA_INSUFICIENTE")


@pytest.mark.parametrize("estado", [None, "I", "C"])
def test_agencia_invalida_409(monkeypatch: pytest.MonkeyPatch, estado):
    _patch_repo(
        monkeypatch,
        cliente=_CLIENTE_ACTIVO,
        riesgo=_RIESGO_APROBADO,
        subproducto=_SUBPRODUCTO_CUENTA,
        agencia=None if estado is None else {"estado": estado},
    )
    with pytest.raises(HTTPException) as exc:
        _abrir_cuenta()
    _assert_http_error(exc, 409, "AGENCIA_INACTIVA")


@pytest.mark.parametrize(
    "payload",
    [
        {**_PAYLOAD, "idAgencia": "1"},
        {**_PAYLOAD, "idAgencia": "TOOLONG"},
        {},
    ],
)
def test_payload_invalido_cta01(payload):
    with pytest.raises(ValidationError):
        CuentaCreate.model_validate(payload)


def test_cta01_moneda_usd_por_defecto_y_rechaza_otras():
    payload_sin_moneda = {k: v for k, v in _PAYLOAD.items() if k != "idMoneda"}
    assert CuentaCreate.model_validate(payload_sin_moneda).id_moneda == ID_MONEDA_USD
    with pytest.raises(ValidationError):
        CuentaCreate.model_validate({**_PAYLOAD, "idMoneda": 978})


# CTA-02


def test_cta02_sin_filtros_resumen_y_orden_predeterminado():
    db = _fake_conn([_cuenta_bd_row(total=2), _cuenta_bd_row(id_cuenta=502, total=2)])
    resultado = service.listar_cuentas(cast(Connection, db))
    assert (resultado.page, resultado.page_size, resultado.total) == (1, 20, 2)
    assert [c.id_cuenta for c in resultado.items] == [501, 502]
    sql, params = db.consultas[0]
    assert params == {
        "id_cliente": None,
        "numero_cuenta": None,
        "estado": None,
        "id_agencia": None,
        "campo": "IdCuenta",
        "direccion": "asc",
        "offset": 0,
        "limite": 20,
    }
    body = resultado.model_dump(mode="json", by_alias=True)
    assert body["pageSize"] == 20
    assert set(body["items"][0]) == {
        "idCuenta",
        "numeroCuenta",
        "idCliente",
        "idProducto",
        "idAgencia",
        "tipoCuenta",
        "estado",
    }
    assert "Saldo" not in sql
    assert len(db.consultas) == 1
    _assert_solo_lectura(db)


@pytest.mark.parametrize(
    ("filtros", "estado_bd"),
    [
        ({"id_cliente": 125}, None),
        ({"numero_cuenta": "00000501"}, None),
        ({"estado": "CERRADA"}, "Cerrada"),
        ({"id_agencia": "001"}, None),
        (
            {
                "id_cliente": 125,
                "numero_cuenta": "00000501",
                "estado": "ACTIVA",
                "id_agencia": "001",
            },
            "Activa",
        ),
    ],
)
def test_cta02_filtros_individuales_y_combinados(filtros, estado_bd):
    db = _fake_conn([_cuenta_row(total=1)])
    service.listar_cuentas(cast(Connection, db), **filtros)
    sql, params = db.consultas[0]
    for nombre, columna in [
        ("id_cliente", "IdCliente"),
        ("numero_cuenta", "NumeroCuenta"),
        ("estado", "Estado"),
        ("id_agencia", "IdAgencia"),
    ]:
        assert params[nombre] == (
            estado_bd if nombre == "estado" else filtros.get(nombre)
        )
        assert f"(:{nombre} IS NULL OR c.{columna} = :{nombre})" in sql
    assert sql.count("AND (:") == 3
    assert "LIKE" not in sql
    assert len(db.consultas) == 1
    _assert_solo_lectura(db)


@pytest.mark.parametrize(
    "valor", ["00000501", "' OR 1=1 --", "%_", "001; DROP TABLE Cuenta"]
)
@pytest.mark.parametrize("filtro", ["numero_cuenta", "id_agencia"])
def test_cta02_cadenas_exactas_ligadas_sin_interpolar(filtro, valor):
    db = _fake_conn([{"id_cuenta": None, "total": 0}])
    service.listar_cuentas(cast(Connection, db), **{filtro: valor})
    sql, params = db.consultas[0]
    assert params[filtro] == valor
    assert isinstance(params[filtro], str)
    assert valor not in sql
    assert "LIKE" not in sql
    _assert_solo_lectura(db)


@pytest.mark.parametrize(
    ("page", "page_size", "total", "id_cliente"),
    [(1, 20, 0, None), (1, 20, 0, 999), (4, 2, 5, None)],
)
def test_cta02_lista_vacia_y_pagina_fuera_de_rango(page, page_size, total, id_cliente):
    db = _fake_conn([{"id_cuenta": None, "total": total}])
    resultado = service.listar_cuentas(
        cast(Connection, db), page=page, page_size=page_size, id_cliente=id_cliente
    )
    assert resultado.items == []
    assert (resultado.page, resultado.page_size, resultado.total) == (
        page,
        page_size,
        total,
    )
    sql, params = db.consultas[0]
    assert (params["offset"], params["limite"]) == (
        (page - 1) * page_size,
        page * page_size,
    )
    assert "COUNT(*) AS total FROM Filtrados" in sql
    assert "LEFT JOIN Filtrados" in sql
    assert len(db.consultas) == 1
    _assert_solo_lectura(db)


@pytest.mark.parametrize("campo", list(service.CAMPOS_ORDEN_CUENTAS))
@pytest.mark.parametrize("direccion", ["asc", "desc"])
def test_cta02_orden_valido_paginacion_y_desempate(campo, direccion):
    db = _fake_conn([_cuenta_row(total=7)])
    resultado = service.listar_cuentas(
        cast(Connection, db), page=2, page_size=3, sort=f"{campo},{direccion}"
    )
    sql, params = db.consultas[0]
    columna = service.CAMPOS_ORDEN_CUENTAS[campo]
    assert (params["campo"], params["direccion"]) == (columna, direccion)
    assert (params["offset"], params["limite"]) == (3, 6)
    orden = " ".join(sql.split())
    alias = "p" if campo == "tipoCuenta" else "c"
    assert (
        f":campo = '{columna}' AND :direccion = '{direccion}' THEN {alias}.{columna} END {direccion.upper()}"
        in orden
    )
    assert "c.IdCuenta ASC ) AS numero_fila" in orden
    assert (resultado.page, resultado.page_size, resultado.total) == (2, 3, 7)
    _assert_solo_lectura(db)


@pytest.mark.parametrize(
    "sort",
    [
        "",
        "idCuenta",
        "idCuenta,",
        ",asc",
        "idCuenta,ASC",
        "idCuenta,otro",
        "desconocido,asc",
        "idCuenta,asc,desc",
        "idCuenta; DROP TABLE Cuenta,asc",
        "numeroCuenta,desc;--",
        " idCuenta,asc",
        "idCuenta,asc ",
        "saldo,asc",
    ],
)
def test_cta02_sort_invalido_antes_de_consultar(sort):
    db = _fake_conn()
    with pytest.raises(HTTPException) as exc:
        service.listar_cuentas(cast(Connection, db), sort=sort)
    _assert_http_error(exc, 400, "SORT_INVALIDO")
    assert db.consultas == []
    _assert_solo_lectura(db)


# Adaptación de la base configurada, sin fabricar moneda ni cambiar el contrato.


@pytest.mark.parametrize(
    ("estado_api", "estado_bd"),
    [
        ("ACTIVA", "Activa"),
        ("INACTIVA", "Inactiva"),
        ("BLOQUEADA", "Bloqueada"),
        ("CERRADA", "Cerrada"),
    ],
)
def test_cta02_traduce_estados_en_ambos_sentidos(estado_api, estado_bd):
    fila = _cuenta_bd_row(estado=estado_bd, total=1)
    original = fila.copy()
    db = _fake_conn([fila])
    resultado = service.listar_cuentas(cast(Connection, db), estado=estado_api)
    assert resultado.items[0].estado == estado_api
    assert db.consultas[0][1]["estado"] == estado_bd
    assert fila == original
    _assert_solo_lectura(db)


def test_repositorio_detalle_usa_producto_sin_fabricar_moneda():
    fila = _cuenta_bd_row(estado="Cerrada", tipo_cuenta="Corriente")
    original = fila.copy()
    db = _fake_conn([fila])
    resultado = repository.obtener_cuenta_por_id(cast(Connection, db), 501)
    assert resultado == {**fila, "estado": "CERRADA"}
    assert resultado is not None
    assert "id_moneda" not in resultado
    assert fila == original
    sql, params = db.consultas[0]
    assert params == {"id_cuenta": 501}
    assert sql.split("WHERE")[1].strip() == "c.IdCuenta = :id_cuenta"
    assert "p.Estado" not in sql  # No excluye productos inactivos.
    assert len(db.consultas) == 1
    _assert_solo_lectura(db)


@pytest.mark.parametrize("consulta", [service.obtener_cuenta, service.obtener_saldo])
@pytest.mark.parametrize("estado", ["Activa", "Inactiva", "Bloqueada", "Cerrada"])
def test_consulta_deriva_usd_sin_columna_por_cuenta(consulta, estado):
    db = _fake_conn([_cuenta_bd_row(estado=estado)])
    resultado = consulta(cast(Connection, db), 501)
    assert resultado.id_moneda == ID_MONEDA_USD
    assert len(db.consultas) == 1
    _assert_solo_lectura(db)


@pytest.mark.parametrize("consulta", [service.obtener_cuenta, service.obtener_saldo])
def test_consulta_siempre_aplica_la_regla_global_usd(consulta):
    db = _fake_conn([_cuenta_row(id_moneda=None)])
    resultado = consulta(cast(Connection, db), 501)
    assert resultado.id_moneda == ID_MONEDA_USD
    _assert_solo_lectura(db)


# CTA-03/CTA-04: la moneda se deriva de la regla global y no de la fila.


@pytest.mark.parametrize("estado", get_args(EstadoCuenta))
def test_cta03_detalle_completo_en_cualquier_estado(estado):
    fila = _cuenta_row(
        estado=estado, saldo=Decimal("1500.25"), saldo_retenido=Decimal("200.10")
    )
    db = _fake_conn([fila])
    resultado = service.obtener_cuenta(cast(Connection, db), 501)
    assert resultado.model_dump() == fila
    assert isinstance(resultado.saldo, Decimal)
    assert isinstance(resultado.saldo_retenido, Decimal)
    body = resultado.model_dump(mode="json", by_alias=True)
    assert body["saldo"] == 1500.25
    assert body["saldoRetenido"] == 200.10
    assert (body["idMoneda"], body["idAgencia"]) == (ID_MONEDA_USD, "001")
    sql, params = db.consultas[0]
    assert params == {"id_cuenta": 501}
    assert sql.split("WHERE")[1].strip() == "c.IdCuenta = :id_cuenta"
    assert len(db.consultas) == 1
    _assert_solo_lectura(db)


@pytest.mark.parametrize("consulta", [service.obtener_cuenta, service.obtener_saldo])
def test_consulta_cuenta_inexistente_404(consulta):
    db = _fake_conn([])
    with pytest.raises(HTTPException) as exc:
        consulta(cast(Connection, db), 999)
    _assert_http_error(exc, 404, "CUENTA_NO_ENCONTRADA")
    assert db.consultas[0][1] == {"id_cuenta": 999}
    assert len(db.consultas) == 1
    _assert_solo_lectura(db)


@pytest.mark.parametrize(
    ("saldo", "retenido", "disponible"),
    [
        ("1500.25", "200.10", "1300.15"),
        ("0.30", "0.10", "0.20"),
        ("10.37", "0.00", "10.37"),
        ("1.23", "1.23", "0.00"),
        ("1.00", "2.13", "-1.13"),
    ],
)
@pytest.mark.parametrize(
    "estado", [e for e in get_args(EstadoCuenta) if e != "CERRADA"]
)
def test_cta04_saldos_decimal_sin_limitar_disponible(
    monkeypatch: pytest.MonkeyPatch, saldo, retenido, disponible, estado
):
    ahora = datetime(2026, 11, 4, 15, 30, tzinfo=UTC)

    class _Reloj:
        @staticmethod
        def now(zona):
            assert zona == UTC
            return ahora

    monkeypatch.setattr(service, "datetime", _Reloj)
    db = _fake_conn(
        [
            _cuenta_row(
                id_cuenta=712,
                id_moneda=978,
                estado=estado,
                saldo=Decimal(saldo),
                saldo_retenido=Decimal(retenido),
            )
        ]
    )
    resultado = service.obtener_saldo(cast(Connection, db), 712)
    assert (resultado.id_cuenta, resultado.id_moneda) == (712, ID_MONEDA_USD)
    for valor, esperado in [
        (resultado.saldo, saldo),
        (resultado.saldo_retenido, retenido),
        (resultado.saldo_disponible, disponible),
    ]:
        assert isinstance(valor, Decimal)
        assert valor == Decimal(esperado)
    assert resultado.fecha_consulta == ahora
    assert resultado.fecha_consulta.tzinfo == UTC
    body = json.loads(resultado.model_dump_json(by_alias=True))
    assert all(
        isinstance(body[campo], (int, float))
        for campo in ("saldo", "saldoRetenido", "saldoDisponible")
    )
    assert body["fechaConsulta"] == "2026-11-04T15:30:00Z"
    assert len(db.consultas) == 1
    assert db.consultas[0][1] == {"id_cuenta": 712}
    _assert_solo_lectura(db)


def test_cta04_cerrada_ceros_sin_modificar_fila_ni_detalle():
    fila = _cuenta_row(
        estado="CERRADA", saldo=Decimal("123.45"), saldo_retenido=Decimal("200.12")
    )
    original = fila.copy()
    db = _fake_conn([fila], [fila])
    resultado = service.obtener_saldo(cast(Connection, db), 501)
    assert (
        resultado.saldo
        == resultado.saldo_retenido
        == resultado.saldo_disponible
        == Decimal("0.00")
    )
    assert (resultado.id_cuenta, resultado.id_moneda) == (501, ID_MONEDA_USD)
    detalle = service.obtener_cuenta(cast(Connection, db), 501)
    assert detalle.saldo == original["saldo"]
    assert detalle.saldo_retenido == original["saldo_retenido"]
    assert fila == original
    assert db.consultas[0] == db.consultas[1]
    _assert_solo_lectura(db)


def test_saldo_rechaza_fecha_sin_zona():
    with pytest.raises(ValidationError):
        SaldoCuenta(
            id_cuenta=501,
            id_moneda=ID_MONEDA_USD,
            saldo=Decimal(0),
            saldo_retenido=Decimal(0),
            saldo_disponible=Decimal(0),
            fecha_consulta=datetime(2026, 11, 4),
        )


# Contrato sin servidor HTTP ni sockets.


def test_consultas_contrato_openapi_sin_sockets():
    contrato = app.openapi()
    for sufijo, operacion, modelo in [
        ("", "CTA02", "PageCuenta"),
        ("/{idCuenta}", "CTA03", "Cuenta"),
        ("/{idCuenta}/saldo", "CTA04", "SaldoCuenta"),
    ]:
        ruta = contrato["paths"][f"/api/v1/cuentas{sufijo}"]["get"]
        assert ruta["operationId"] == operacion
        assert ruta["x-roles"] == ["ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"]
        assert ruta["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith(f"/{modelo}")
        for status in ("400", "401", "403", "404"):
            problema = ruta["responses"][status]["content"]["application/problem+json"][
                "schema"
            ]
            assert {"type", "title", "status", "code", "detail", "traceId"} <= set(
                problema["required"]
            )
    parametros = {
        p["name"]: p["schema"]
        for p in contrato["paths"]["/api/v1/cuentas"]["get"]["parameters"]
    }
    assert set(parametros) == {
        "idCliente",
        "numeroCuenta",
        "estado",
        "idAgencia",
        "page",
        "pageSize",
        "sort",
    }
    assert {"type": "string"} in parametros["numeroCuenta"]["anyOf"]
    assert {
        "type": "string",
        "minLength": 3,
        "maxLength": 3,
    } in parametros["idAgencia"]["anyOf"]
    assert parametros["page"]["default"] == parametros["page"]["minimum"] == 1
    assert parametros["pageSize"]["default"] == 20
    assert parametros["pageSize"]["minimum"] == 1
    assert parametros["pageSize"]["maximum"] == 100
    estados = parametros["estado"]["anyOf"][0]["enum"]
    assert estados == list(get_args(EstadoCuenta))
    assert "CERRADA" in estados and "Cerrada" not in estados
    esquemas = contrato["components"]["schemas"]
    assert esquemas["PageCuenta"]["properties"]["items"]["items"]["$ref"].endswith(
        "/CuentaResumen"
    )
    for modelo in ("Cuenta", "SaldoCuenta"):
        for campo in ("saldo", "saldoRetenido"):
            assert esquemas[modelo]["properties"][campo]["type"] == "number"
    assert esquemas["SaldoCuenta"]["properties"]["saldoDisponible"]["type"] == "number"
    assert esquemas["Cuenta"]["properties"]["idMoneda"]["const"] == ID_MONEDA_USD
    assert esquemas["SaldoCuenta"]["properties"]["idMoneda"]["const"] == ID_MONEDA_USD
    assert esquemas["CuentaCreate"]["properties"]["idMoneda"] == {
        "type": "integer",
        "const": ID_MONEDA_USD,
        "default": ID_MONEDA_USD,
        "title": "Idmoneda",
    }
    assert (
        esquemas["SaldoCuenta"]["properties"]["fechaConsulta"]["format"] == "date-time"
    )
    assert set(esquemas["Cuenta"]["properties"]) == set(
        Cuenta(**_cuenta_row()).model_dump(by_alias=True)
    )
    consultas = router._consultas_router.routes
    assert len(consultas) == 3
    assert all(isinstance(r, ProblemDetailsRoute) for r in consultas)
    assert any(d.dependency is require_auth for d in router.router.dependencies)
    apertura = contrato["paths"]["/api/v1/cuentas"]["post"]
    assert apertura["operationId"] == "CTA01"
    assert apertura["x-roles"] == ["ASESOR", "ADMIN"]
    assert apertura["responses"]["201"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/Cuenta")
    for status in ("400", "401", "403", "409", "422"):
        assert "application/problem+json" in apertura["responses"][status]["content"]
    cuerpo = esquemas["CuentaCreate"]
    assert set(cuerpo["required"]) == {
        "idCliente",
        "idSubProducto",
        "idAgencia",
        "montoInicial",
    }
    assert set(cuerpo["properties"]) == {*cuerpo["required"], "idMoneda"}
    assert all(
        isinstance(r, ProblemDetailsRoute) for r in router._apertura_router.routes
    )


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "page=-1",
        "pageSize=0",
        "pageSize=101",
        "pageSize=abc",
        "idCliente=abc",
        "idAgencia=1",
        "estado=Cerrada",
        "estado=PENDIENTE_ACTIVACION",
        "estado=DESCONOCIDO",
    ],
)
def test_cta02_validacion_real_de_query_sin_sockets(query):
    ruta = next(r for r in router._consultas_router.routes if isinstance(r, APIRoute))
    _, errores = request_params_to_args(ruta.dependant.query_params, QueryParams(query))
    assert errores


def test_cta02_aliases_query_y_ceros_iniciales():
    ruta = next(r for r in router._consultas_router.routes if isinstance(r, APIRoute))
    valores, errores = request_params_to_args(
        ruta.dependant.query_params,
        QueryParams(
            "idCliente=125&numeroCuenta=00000501&idAgencia=001&estado=CERRADA&page=2&pageSize=100&sort=idCuenta,desc"
        ),
    )
    assert not errores
    assert valores == {
        "id_cliente": 125,
        "numero_cuenta": "00000501",
        "id_agencia": "001",
        "estado": "CERRADA",
        "page": 2,
        "page_size": 100,
        "sort": "idCuenta,desc",
    }


def test_router_apertura_conserva_payload_y_creado_por(monkeypatch: pytest.MonkeyPatch):
    db = _fake_conn()
    payload = CuentaCreate(**_PAYLOAD)
    cuenta = Cuenta(**_cuenta_row())

    def abrir(conn, recibido, creado_por):
        assert conn is db
        assert recibido is payload
        assert creado_por == 12
        return cuenta

    monkeypatch.setattr(service, "abrir_cuenta", abrir)
    usuario = Usuario(
        id_usuario="user_prueba",
        id_sesion="session_prueba",
        id_organizacion=None,
        nombre="Asesor",
        email="asesor@example.ec",
        roles=("ASESOR",),
        permisos=(),
        id_agencia="001",
    )
    assert router.abrir_cuenta(payload, usuario, 12, cast(Connection, db)) is cuenta


@pytest.mark.parametrize(
    "filtros",
    [
        {},
        {
            "id_cliente": 125,
            "numero_cuenta": "00000501",
            "estado": "BLOQUEADA",
            "id_agencia": "001",
            "page": 2,
            "page_size": 3,
            "sort": "numeroCuenta,desc",
        },
    ],
)
def test_router_listado_propaga_parametros(filtros):
    db = _fake_conn([_cuenta_row(total=1)])
    resultado = router.listar_cuentas(cast(Connection, db), **filtros)
    params = db.consultas[0][1]
    for nombre in ("id_cliente", "numero_cuenta", "estado", "id_agencia"):
        esperado = (
            "Bloqueada" if nombre == "estado" and filtros else filtros.get(nombre)
        )
        assert params[nombre] == esperado
    assert resultado.page == filtros.get("page", 1)
    assert resultado.page_size == filtros.get("page_size", 20)
    assert params["campo"] == ("NumeroCuenta" if filtros else "IdCuenta")
    assert params["direccion"] == ("desc" if filtros else "asc")
    _assert_solo_lectura(db)


@pytest.mark.parametrize("consulta", [router.obtener_cuenta, router.obtener_saldo])
def test_router_detalle_y_saldo_propagan_id(consulta):
    db = _fake_conn([_cuenta_row(id_cuenta=712)])
    resultado = consulta(712, cast(Connection, db))
    assert resultado.id_cuenta == 712
    assert db.consultas[0][1] == {"id_cuenta": 712}
    _assert_solo_lectura(db)


@pytest.mark.parametrize("consulta", ["sort", "cuenta", "saldo"])
def test_consultas_errores_problem_details_sin_sockets(
    monkeypatch: pytest.MonkeyPatch, consulta
):
    db = _fake_conn() if consulta == "sort" else _fake_conn([])

    async def ejecutar(request):
        if consulta == "sort":
            router.listar_cuentas(cast(Connection, db), sort="idCuenta,otro")
        elif consulta == "cuenta":
            router.obtener_cuenta(999, cast(Connection, db))
        else:
            router.obtener_saldo(999, cast(Connection, db))
        raise AssertionError("La consulta debía fallar")

    # El wrapper real convierte la excepción de servicio; se omite solo el motor DI.
    monkeypatch.setattr(APIRoute, "get_route_handler", lambda self: ejecutar)
    ruta = next(
        r for r in router._consultas_router.routes if isinstance(r, ProblemDetailsRoute)
    )
    respuesta = asyncio.run(
        ruta.get_route_handler()(
            Request(
                {"type": "http", "headers": [], "state": {"trace_id": "cuentas-test"}}
            )
        )
    )
    body = json.loads(bytes(respuesta.body))
    assert respuesta.media_type == "application/problem+json"
    if consulta == "sort":
        assert respuesta.status_code == 400
        assert body["code"] == "SORT_INVALIDO"
    else:
        assert respuesta.status_code == 404
        assert body["code"] == "CUENTA_NO_ENCONTRADA"
    assert {"type", "title", "status", "code", "detail", "traceId"} <= body.keys()
    assert body["traceId"] == "cuentas-test"
    _assert_solo_lectura(db)


# CTA-05 / CTA-07 / CTA-08 / CTA-09: se mantienen todas las pruebas en este archivo.
_PERMITIDAS = {
    ("ACTIVA", "INACTIVA"),
    ("INACTIVA", "ACTIVA"),
    ("ACTIVA", "BLOQUEADA"),
    ("BLOQUEADA", "ACTIVA"),
    ("ACTIVA", "CERRADA"),
    ("INACTIVA", "CERRADA"),
}
_ESTADO_BD = {
    "ACTIVA": "Activa",
    "INACTIVA": "Inactiva",
    "BLOQUEADA": "Bloqueada",
    "CERRADA": "Cerrada",
}
_CUPO_BODY = {
    "cupoDiario": "400.00",
    "cupoMensual": "5000.00",
    "montoMaxTransaccion": "200.00",
    "maxTransaccionesDia": 10,
}


def _cupo_row(**cambios):
    return {
        "id_canal": 1,
        "origen": "Personalizado",
        "cupo_diario": Decimal("400.00"),
        "cupo_mensual": Decimal("5000.00"),
        "monto_max_transaccion": Decimal("200.00"),
        "max_transacciones_dia": 10,
        "fecha_vigencia": None,
        "consumido_hoy": Decimal("100.00"),
        "consumido_mes": Decimal("1200.00"),
        **cambios,
    }


def _historial_row(**cambios):
    return {
        "id_cupo_mod_his": 103,
        "cupo_diario_anterior": None,
        "cupo_diario_nuevo": Decimal("400.00"),
        "cupo_mensual_anterior": None,
        "cupo_mensual_nuevo": Decimal("5000.00"),
        "monto_max_tx_anterior": None,
        "monto_max_tx_nuevo": Decimal("200.00"),
        "modificado_por": 12,
        "fecha_modificacion": datetime(
            2026, 11, 4, 15, 30, tzinfo=timezone(timedelta(hours=-5))
        ),
        "total": 1,
        **cambios,
    }


def _cambiar(
    db: _FakeConn,
    estado: EstadoCuenta = "CERRADA",
    motivo: str = "Solicitud del titular",
) -> Cuenta:
    return service.cambiar_estado_cuenta(
        cast(Connection, db),
        501,
        CuentaEstadoUpdate(estado=estado, motivo=motivo),
        12,
        "127.0.0.1",
        "cta05-test",
    )


@pytest.mark.parametrize("anterior", list(_ESTADO_BD))
@pytest.mark.parametrize("nuevo", list(_ESTADO_BD))
def test_cta05_matriz_completa(anterior, nuevo, eventos_auditados):
    respuestas = [[_cuenta_bd_row(estado=_ESTADO_BD[anterior])]]
    valida = (anterior, nuevo) in _PERMITIDAS
    if valida:
        if nuevo == "CERRADA":
            respuestas.append([])
        respuestas.extend([[], [_cuenta_bd_row(estado=_ESTADO_BD[nuevo])]])
    db = _fake_conn(*respuestas)
    if valida:
        resultado = _cambiar(db, nuevo)
        assert resultado.estado == nuevo and resultado.id_moneda == 840
        assert db.commits == 1 and db.rollbacks == 0
        assert not db.respuestas
        sql, parametros = db.consultas[-2]
        assert parametros == {"id_cuenta": 501, "estado": _ESTADO_BD[nuevo]}
        assert "FechaCierre = CASE" in sql
        assert "AT TIME ZONE 'SA Pacific Standard Time'" in sql
        assert all("Tarjeta." not in sql for sql, _ in db.consultas)
    else:
        with pytest.raises(HTTPException) as exc:
            _cambiar(db, nuevo)
        _assert_http_error(exc, 409, "TRANSICION_INVALIDA")
        assert db.commits == 0 and db.rollbacks == 1
        assert len(db.consultas) == 1
    assert "WITH (XLOCK, HOLDLOCK)" in db.consultas[0][0]
    (evento,) = eventos_auditados
    assert evento.usuario == 12 and evento.ip == "127.0.0.1"
    assert f"estadoAnterior={anterior}" in evento.descripcion
    assert f"estadoNuevo={nuevo}" in evento.descripcion
    assert "motivo=Solicitud del titular" in evento.descripcion
    assert "traceId=cta05-test" in evento.descripcion
    assert evento.resultado == ("Exitoso" if valida else "Fallido")


@pytest.mark.parametrize("saldo,retenido", [("0.01", "0"), ("0", "0.01"), ("1", "1")])
def test_cta05_cierre_con_importes(saldo, retenido):
    db = _fake_conn(
        [_cuenta_bd_row(saldo=Decimal(saldo), saldo_retenido=Decimal(retenido))]
    )
    with pytest.raises(HTTPException) as exc:
        _cambiar(db)
    _assert_http_error(exc, 409, "CUENTA_CON_SALDO")
    assert db.rollbacks == 1 and db.commits == 0 and len(db.consultas) == 1


def test_cta05_cuenta_inexistente():
    db = _fake_conn([])
    with pytest.raises(HTTPException) as exc:
        _cambiar(db)
    _assert_http_error(exc, 404, "CUENTA_NO_ENCONTRADA")
    assert db.rollbacks == 1 and db.commits == 0


@pytest.mark.parametrize(
    "estado,deuda,bloquea",
    [
        ("PENDIENTE", False, True),
        ("DESEMBOLSADO", True, True),
        ("DESEMBOLSADO", False, False),
        ("REVERSADO", True, False),
    ],
)
def test_cta05_credito_vinculado_y_deuda_real(monkeypatch, estado, deuda, bloquea):
    respuestas = [[_cuenta_bd_row()], [{"id_solicitud": 99, "estado": estado}]]
    if not bloquea:
        respuestas.extend([[], [_cuenta_bd_row(estado="Cerrada")]])
    db = _fake_conn(*respuestas)
    llamadas = []

    def tiene_deuda(conn, solicitud):
        assert conn is db and solicitud == 99
        llamadas.append(solicitud)
        return deuda

    monkeypatch.setattr(service.clientes_service, "credito_tiene_deuda", tiene_deuda)
    if bloquea:
        with pytest.raises(HTTPException) as exc:
            _cambiar(db)
        _assert_http_error(exc, 409, "CUENTA_CON_CREDITO_VIGENTE")
        assert db.rollbacks == 1 and db.commits == 0
    else:
        assert _cambiar(db).estado == "CERRADA"
    sql, params = db.consultas[1]
    assert "IdCuentaDesembolso = :id_cuenta" in sql
    assert "WITH (UPDLOCK, HOLDLOCK)" in sql
    assert params == {"id_cuenta": 501}
    assert llamadas == ([99] if estado == "DESEMBOLSADO" else [])


@pytest.mark.parametrize(
    "etapa",
    [
        "bloquear_cuenta",
        "desembolsos_de_cuenta",
        "actualizar_estado_cuenta",
        "obtener_cuenta_por_id",
        "commit",
    ],
)
def test_cta05_rollback_y_auditoria_ante_cualquier_fallo(
    monkeypatch, etapa, eventos_auditados
):
    db = _fake_conn([_cuenta_bd_row()], [], [], [_cuenta_bd_row(estado="Cerrada")])

    def fallar(*args, **kwargs):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(db if etapa == "commit" else repository, etapa, fallar)
    with pytest.raises(RuntimeError):
        _cambiar(db)
    assert db.rollbacks == 1 and db.commits == 0
    assert eventos_auditados[-1].resultado == "Fallido"


@pytest.mark.parametrize("motivo", ["", "   ", "x" * 301, "a\nb"])
def test_cta05_motivo_invalido(motivo):
    with pytest.raises(ValidationError):
        CuentaEstadoUpdate(estado="ACTIVA", motivo=motivo)


@pytest.mark.parametrize("campo", ["usuario", "modificadoPor", "creadoPor"])
def test_cta05_usuario_nunca_viene_del_body(campo):
    with pytest.raises(ValidationError):
        CuentaEstadoUpdate.model_validate(
            {"estado": "ACTIVA", "motivo": "válido", campo: 999}
        )


@pytest.mark.parametrize(
    "origen,vigencia", [("Personalizado", date(2026, 12, 1)), ("Producto", None)]
)
@pytest.mark.parametrize("hoy,mes", [("100.25", "1200.50"), ("0", "0")])
def test_cta07_efectivo_y_consumo_decimal_solo_lectura(origen, vigencia, hoy, mes):
    db = _fake_conn(
        [_cuenta_bd_row()],
        [
            _cupo_row(
                origen=origen,
                fecha_vigencia=vigencia,
                consumido_hoy=Decimal(hoy),
                consumido_mes=Decimal(mes),
            )
        ],
    )
    (resultado,) = service.obtener_cupos(cast(Connection, db), 501)
    assert resultado.origen == origen and resultado.fecha_vigencia == vigencia
    assert resultado.consumido_hoy == Decimal(
        hoy
    ) and resultado.consumido_mes == Decimal(mes)
    assert isinstance(resultado.cupo_diario, Decimal)
    assert db.commits == db.rollbacks == 0
    sql, params = db.consultas[-1]
    assert "Canal.fn_CupoVigente(:id_cuenta, canal.IdCanal)" in sql
    assert params == {"id_cuenta": 501, "id_canal": None}
    assert "t.Estado = 'Completada' AND t.TipoOperacion = 'Normal'" in sql
    assert "tt.Naturaleza = 'D'" in sql
    assert "t.FechaHoraSistema >= l.inicio_mes AND t.FechaHoraSistema < l.manana" in sql
    assert "t.FechaHoraSistema >= l.hoy" in sql
    assert (
        "CAST(t.FechaHoraSistema" not in sql
        and "CONVERT(date, t.FechaHoraSistema" not in sql
    )
    assert "COALESCE(cons.consumido_hoy, 0)" in sql
    assert all(p not in sql.upper() for p in ("INSERT ", "UPDATE ", "DELETE ", "EXEC "))


def test_cta07_cuenta_inexistente_y_sin_cupos():
    db = _fake_conn([])
    with pytest.raises(HTTPException) as exc:
        service.obtener_cupos(cast(Connection, db), 501)
    _assert_http_error(exc, 404, "CUENTA_NO_ENCONTRADA")
    assert db.commits == db.rollbacks == 0
    db = _fake_conn([_cuenta_bd_row()], [])
    assert service.obtener_cupos(cast(Connection, db), 501) == []
    assert db.commits == db.rollbacks == 0


def _db_actualizar_cupo(anterior=None, efectivo=None, producto=None):
    return _fake_conn(
        [_cuenta_bd_row()],
        [{"id_canal": 1}],
        [
            producto
            or _cupo_row(
                cupo_diario=Decimal(1000),
                cupo_mensual=Decimal(10000),
                monto_max_transaccion=Decimal(500),
                max_transacciones_dia=20,
            )
        ],
        [anterior] if anterior else [],
        [],
        [],
        [efectivo or _cupo_row()],
    )


def _actualizar(db, **cambios):
    return service.actualizar_cupo(
        cast(Connection, db),
        501,
        1,
        CupoUpdate.model_validate(_CUPO_BODY | cambios),
        12,
    )


@pytest.mark.parametrize("existe", [False, True])
@pytest.mark.parametrize("vencido", [False, True])
def test_cta08_crea_actualiza_historial_una_vez_y_respuesta_efectiva(existe, vencido):
    anterior = _cupo_row(cupo_diario=Decimal(300)) if existe else None
    efectivo = _cupo_row(origen="Producto") if vencido else _cupo_row()
    db = _db_actualizar_cupo(anterior, efectivo)
    resultado = _actualizar(db, fechaVigencia="2020-01-01" if vencido else None)
    assert resultado.origen == ("Producto" if vencido else "Personalizado")
    assert db.commits == 1 and db.rollbacks == 0 and not db.respuestas
    assert (
        len([s for s, _ in db.consultas if "INSERT INTO Canal.CuposModHis" in s]) == 1
    )
    sql, params = db.consultas[4]
    assert (
        "UPDATE Canal.CanalCupoClienteCustom"
        if existe
        else "INSERT INTO Canal.CanalCupoClienteCustom"
    ) in sql
    assert params["modificado_por"] == 12
    assert params["fecha_vigencia"] == (date(2020, 1, 1) if vencido else None)
    assert "Estado = 'A'" in sql or "'A', :modificado_por" in sql
    sql, params = db.consultas[5]
    assert params["diario_anterior"] == (Decimal(300) if existe else None)
    assert params["cupo_diario"] == Decimal("400.00") and params["modificado_por"] == 12
    assert "IdCanalCupoCliente" in sql and "IdCanalCupo" in sql
    assert "p.IdSubProducto = c.IdSubProducto" in db.consultas[2][0]
    assert "WITH (HOLDLOCK)" in db.consultas[2][0]
    assert "WITH (UPDLOCK, HOLDLOCK)" in db.consultas[3][0]
    assert db.consultas[-1][1] == {"id_cuenta": 501, "id_canal": 1}


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("cupoDiario", "1001"),
        ("cupoMensual", "10001"),
        ("montoMaxTransaccion", "501"),
        ("maxTransaccionesDia", 21),
    ],
)
def test_cta08_cada_tope_maximo(campo, valor):
    body = {
        "cupoDiario": "1000",
        "cupoMensual": "10000",
        "montoMaxTransaccion": "500",
        "maxTransaccionesDia": 20,
        campo: valor,
    }
    db = _db_actualizar_cupo()
    with pytest.raises(HTTPException) as exc:
        _actualizar(db, **body)
    _assert_http_error(exc, 422, "CUPO_SUPERA_MAXIMO_PRODUCTO")
    assert db.rollbacks == 1 and db.commits == 0 and len(db.consultas) == 3


@pytest.mark.parametrize(
    "cambios", [{"montoMaxTransaccion": "401"}, {"cupoMensual": "399"}]
)
def test_cta08_cupos_inconsistentes(cambios):
    db = _db_actualizar_cupo()
    with pytest.raises(HTTPException) as exc:
        _actualizar(db, **cambios)
    _assert_http_error(exc, 422, "CUPOS_INCONSISTENTES")
    assert db.rollbacks == 1 and db.commits == 0


@pytest.mark.parametrize(
    "etapa,codigo",
    [
        ("cuenta", "CUENTA_NO_ENCONTRADA"),
        ("canal", "CANAL_NO_ENCONTRADO"),
        ("producto", "CUPO_PRODUCTO_NO_CONFIGURADO"),
    ],
)
def test_cta08_recursos_ausentes(etapa, codigo):
    db = _db_actualizar_cupo()
    db.respuestas[{"cuenta": 0, "canal": 1, "producto": 2}[etapa]] = []
    with pytest.raises(HTTPException) as exc:
        _actualizar(db)
    _assert_http_error(exc, 422 if etapa == "producto" else 404, codigo)
    assert db.commits == 0 and db.rollbacks == 1


@pytest.mark.parametrize(
    "etapa",
    [
        "bloquear_cuenta",
        "obtener_canal",
        "bloquear_cupo_producto",
        "bloquear_cupo_personalizado",
        "guardar_cupo_personalizado",
        "insertar_historial_cupo",
        "consultar_cupos_efectivos",
        "commit",
    ],
)
def test_cta08_rollback_en_cada_etapa(monkeypatch, etapa):
    db = _db_actualizar_cupo()

    def fallar(*args, **kwargs):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(db if etapa == "commit" else repository, etapa, fallar)
    with pytest.raises(RuntimeError):
        _actualizar(db)
    assert db.commits == 0 and db.rollbacks == 1


@pytest.mark.parametrize(
    "filas", [[], [_cupo_row(), _cupo_row(id_canal=2)], [_cupo_row(origen="invalido")]]
)
def test_cta08_no_confirma_sin_respuesta_valida(filas):
    db = _db_actualizar_cupo()
    db.respuestas[-1] = filas
    with pytest.raises((HTTPException, ValidationError)):
        _actualizar(db)
    assert db.commits == 0 and db.rollbacks == 1


@pytest.mark.parametrize(
    "cambios",
    [
        {"cupoDiario": "-0.01"},
        {"cupoMensual": "0.001"},
        {"montoMaxTransaccion": "NaN"},
        {"maxTransaccionesDia": 0},
        {"maxTransaccionesDia": True},
        {"maxTransaccionesDia": 1.5},
        {"maxTransaccionesDia": 32768},
        {"modificadoPor": 999},
    ],
)
def test_cta08_body_invalido(cambios):
    with pytest.raises(ValidationError):
        CupoUpdate.model_validate(_CUPO_BODY | cambios)


def test_cta08_error_de_tope_conserva_compatibilidad_global():
    from app.core.api.errors import traducir_error_bd

    error = DBAPIError(
        "SQL SECRETO", {}, Exception("42000", "privado (52003) (SQLExecDirectW)")
    )
    general = traducir_error_bd(error)
    assert general.status_code == 422
    assert isinstance(general.detail, dict)
    assert general.detail.get("code") == "CUPO_EXCEDE_PRODUCTO"

    especifico = traducir_error_bd(error, operacion="CTA08")
    assert especifico.status_code == 422
    assert isinstance(especifico.detail, dict)
    assert especifico.detail.get("code") == "CUPO_SUPERA_MAXIMO_PRODUCTO"


@pytest.mark.parametrize("campo", ["cupoDiario", "cupoMensual", "montoMaxTransaccion"])
@pytest.mark.parametrize("valor", [0, "0.00", "-0.01"])
def test_cta08_rechaza_cupos_no_positivos_antes_del_servicio(
    sesion_cuentas, monkeypatch, campo, valor
):

    usuario, dependencia = sesion_cuentas
    app.dependency_overrides[dependencia] = lambda: usuario

    def no_ejecutar(*args, **kwargs):
        raise AssertionError("Un cupo no positivo debe rechazarse antes del servicio")

    monkeypatch.setattr(service, "actualizar_cupo", no_ejecutar)
    respuesta = asyncio.run(
        _http_cuentas("PUT", "/api/v1/cuentas/501/cupos/1", _CUPO_BODY | {campo: valor})
    )
    assert respuesta.status_code == 400
    assert respuesta.headers["content-type"].startswith("application/problem+json")
    assert respuesta.json()["code"] == "DATOS_INVALIDOS"
    assert respuesta.json()["errors"][0]["field"] == campo


def test_cta08_admite_el_minimo_positivo_representable_en_la_base():
    importe = Decimal("0.01")
    efectivo = _cupo_row(
        cupo_diario=importe,
        cupo_mensual=importe,
        monto_max_transaccion=importe,
        max_transacciones_dia=1,
    )
    db = _db_actualizar_cupo(efectivo=efectivo)
    resultado = _actualizar(
        db,
        cupoDiario="0.01",
        cupoMensual="0.01",
        montoMaxTransaccion="0.01",
        maxTransaccionesDia=1,
    )
    assert resultado.cupo_diario == resultado.cupo_mensual == importe
    assert resultado.monto_max_transaccion == importe
    parametros = db.consultas[4][1]
    for campo in ("cupo_diario", "cupo_mensual", "monto_max_transaccion"):
        assert parametros[campo] == importe
    assert db.commits == 1 and db.rollbacks == 0


def test_cta08_openapi_publica_importes_estrictamente_positivos():
    propiedades = app.openapi()["components"]["schemas"]["CupoUpdate"]["properties"]
    for campo in ("cupoDiario", "cupoMensual", "montoMaxTransaccion"):
        numerico = next(p for p in propiedades[campo]["anyOf"] if p["type"] == "number")
        assert numerico["exclusiveMinimum"] == 0
        assert "minimum" not in numerico


@pytest.mark.parametrize(
    "page,total,filas",
    [
        (1, 1, [_historial_row()]),
        (7, 6, [{"id_cupo_mod_his": None, "total": 6}]),
        (1, 0, [{"id_cupo_mod_his": None, "total": 0}]),
    ],
)
def test_cta09_pagina_total_filtro_y_orden_estable(page, total, filas):
    db = _fake_conn([_cuenta_bd_row()], [{"id_canal": 1}], filas)
    respuesta = service.obtener_historial_cupo(cast(Connection, db), 501, 1, page=page)
    assert respuesta.total == total and respuesta.page == page
    assert len(respuesta.items) == (1 if page == total == 1 else 0)
    sql, params = db.consultas[-1]
    assert params == {
        "id_cuenta": 501,
        "id_canal": 1,
        "campo": "FechaModificacion",
        "direccion": "desc",
        "offset": (page - 1) * 20,
        "limite": page * 20,
    }
    assert "cc.IdCuenta = :id_cuenta AND cc.IdCanal = :id_canal" in sql
    assert "cc.IdCanalCupo = h.IdCanalCupoCliente" in sql
    assert "THEN h.FechaModificacion END DESC" in sql and "h.IdCupoModHis DESC" in sql
    assert "LEFT JOIN Historial" in sql
    if respuesta.items:
        assert respuesta.items[0].fecha_modificacion.utcoffset() == timedelta(hours=-5)
    assert db.commits == db.rollbacks == 0


@pytest.mark.parametrize("campo", ["fechaModificacion", "idCupoModHis"])
@pytest.mark.parametrize("direccion", ["asc", "desc"])
def test_cta09_sort_valido(campo, direccion):
    db = _fake_conn([_cuenta_bd_row()], [{"id_canal": 1}], [])
    service.obtener_historial_cupo(
        cast(Connection, db), 501, 1, sort=f"{campo},{direccion}"
    )
    sql, params = db.consultas[-1]
    assert params["campo"] == campo[0].upper() + campo[1:]
    assert params["direccion"] == direccion
    assert f"{campo},{direccion}" not in sql


@pytest.mark.parametrize(
    "sort",
    [
        "",
        "FechaModificacion,desc",
        "fechaModificacion,DESC",
        "fechaModificacion",
        "idCupoModHis,desc;DROP TABLE Canal.CuposModHis",
        "idCupoModHis,asc,desc",
        "idCuenta,asc",
    ],
)
def test_cta09_sort_invalido_o_inyeccion_no_consulta(sort):
    db = _fake_conn()
    with pytest.raises(HTTPException) as exc:
        service.obtener_historial_cupo(cast(Connection, db), 501, 1, sort=sort)
    _assert_http_error(exc, 400, "SORT_INVALIDO")
    assert not db.consultas and db.commits == db.rollbacks == 0


@pytest.mark.parametrize("cuenta", [False, True])
def test_cta09_cuenta_o_canal_inexistente(cuenta):
    db = _fake_conn([_cuenta_bd_row()], []) if cuenta else _fake_conn([])
    with pytest.raises(HTTPException) as exc:
        service.obtener_historial_cupo(cast(Connection, db), 501, 1)
    _assert_http_error(
        exc, 404, "CANAL_NO_ENCONTRADO" if cuenta else "CUENTA_NO_ENCONTRADA"
    )
    assert db.commits == db.rollbacks == 0


async def _http_cuentas(method, path, body=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        return await client.request(
            method, path, json=body, headers={"X-Request-Id": "cuentas-http"}
        )


@pytest.fixture
def sesion_cuentas(monkeypatch):
    from app.core.database.db import cooperativa
    from app.core.security.auth import usuario_actual

    usuario = Usuario(
        id_usuario="user_cta",
        id_sesion="ses_cta",
        id_organizacion=None,
        nombre="Interno",
        email="interno@example.ec",
        roles=("ADMIN",),
        permisos=(),
        id_agencia="001",
        id_interno=12,
    )
    monkeypatch.setattr(
        service,
        "cambiar_estado_cuenta",
        lambda *a: Cuenta(**_cuenta_row(estado="BLOQUEADA")),
    )
    monkeypatch.setattr(
        service, "obtener_cupos", lambda *a: [service.CupoEfectivo(**_cupo_row())]
    )
    monkeypatch.setattr(
        service, "actualizar_cupo", lambda *a: service.CupoEfectivo(**_cupo_row())
    )
    monkeypatch.setattr(
        service,
        "obtener_historial_cupo",
        lambda *a, **k: service.PageCupoHistorial(
            items=[], page=1, page_size=20, total=0
        ),
    )
    app.dependency_overrides[cooperativa] = lambda: None
    yield usuario, usuario_actual
    app.dependency_overrides.clear()


_RUTAS_NUEVAS = [
    (
        "PATCH",
        "/api/v1/cuentas/501/estado",
        {"estado": "BLOQUEADA", "motivo": "Solicitud"},
        {"ASESOR", "SUPERVISOR", "ADMIN"},
    ),
    ("GET", "/api/v1/cuentas/501/cupos", None, {"ASESOR", "SUPERVISOR", "ADMIN"}),
    ("PUT", "/api/v1/cuentas/501/cupos/1", _CUPO_BODY, {"SUPERVISOR", "ADMIN"}),
    (
        "GET",
        "/api/v1/cuentas/501/cupos/1/historial",
        None,
        {"SUPERVISOR", "AUDITOR", "ADMIN"},
    ),
]


@pytest.mark.parametrize("method,path,body,permitidos", _RUTAS_NUEVAS)
@pytest.mark.parametrize(
    "rol",
    [
        "ASESOR",
        "SUPERVISOR",
        "ADMIN",
        "AUDITOR",
        "CAJERO",
        "CONTADOR",
        "APROBADOR_CREDITO",
    ],
)
def test_cta_roles_efectivos_http(
    sesion_cuentas, monkeypatch, method, path, body, permitidos, rol
):
    from dataclasses import replace

    usuario, dependencia = sesion_cuentas
    app.dependency_overrides[dependencia] = lambda: replace(usuario, roles=(rol,))
    respuesta = asyncio.run(_http_cuentas(method, path, body))
    assert respuesta.status_code == (200 if rol in permitidos else 403)
    if rol not in permitidos:
        assert respuesta.json()["code"] == "SIN_PERMISO"
        assert respuesta.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("method,path,body,permitidos", _RUTAS_NUEVAS)
def test_cta_sin_sesion_401(sesion_cuentas, method, path, body, permitidos):
    respuesta = asyncio.run(_http_cuentas(method, path, body))
    assert respuesta.status_code == 401
    assert respuesta.json()["traceId"] == "cuentas-http"


@pytest.mark.parametrize("index", [0, 2])
def test_cta_escrituras_exigen_usuario_auditoria_real(
    sesion_cuentas, monkeypatch, index
):

    usuario, dependencia = sesion_cuentas
    from dataclasses import replace

    app.dependency_overrides[dependencia] = lambda: replace(usuario, id_interno=None)
    method, path, body, _ = _RUTAS_NUEVAS[index]
    respuesta = asyncio.run(_http_cuentas(method, path, body))
    assert (
        respuesta.status_code == 403
        # require_auth lo rechaza antes de la ruta
        and respuesta.json()["code"] == "USUARIO_NO_REGISTRADO"
    )


def test_cta05_router_propaga_identidad_ip_y_traza(sesion_cuentas, monkeypatch):

    usuario, dependencia = sesion_cuentas
    app.dependency_overrides[dependencia] = lambda: usuario
    llamadas = []

    def cambiar(*args):
        llamadas.append(args)
        return Cuenta(**_cuenta_row(estado="BLOQUEADA"))

    monkeypatch.setattr(service, "cambiar_estado_cuenta", cambiar)
    respuesta = asyncio.run(_http_cuentas(*_RUTAS_NUEVAS[0][:3]))
    assert respuesta.status_code == 200
    assert llamadas[0][1] == 501 and llamadas[0][3:] == (
        12,
        "127.0.0.1",
        "cuentas-http",
    )


def test_cta_nuevos_contratos_openapi():
    contrato = app.openapi()
    for method, path, _, roles in _RUTAS_NUEVAS:
        path = path.replace("/501", "/{idCuenta}").replace("/1/", "/{idCanal}/")
        if path.endswith("/cupos/1"):
            path = path[:-1] + "{idCanal}"
        op = contrato["paths"][path][method.lower()]
        esperado = {"PATCH": "CTA05", "PUT": "CTA08"}.get(
            method, "CTA09" if "historial" in path else "CTA07"
        )
        assert op["operationId"] == esperado and set(op["x-roles"]) == roles
        assert op["security"]
        for status in ("400", "401", "403", "404", "409", "422", "500"):
            assert "application/problem+json" in op["responses"][status]["content"]
    esquemas = contrato["components"]["schemas"]
    assert set(esquemas["CuentaEstadoUpdate"]["properties"]) == {"estado", "motivo"}
    assert esquemas["CuentaEstadoUpdate"]["properties"]["estado"]["enum"] == list(
        _ESTADO_BD
    )
    # Pydantic distingue esquemas de entrada (Decimal) y salida (Money).
    efectivo = esquemas["CupoEfectivo"]["properties"]
    assert set(efectivo) == {
        "idCanal",
        "origen",
        "cupoDiario",
        "cupoMensual",
        "montoMaxTransaccion",
        "maxTransaccionesDia",
        "fechaVigencia",
        "consumidoHoy",
        "consumidoMes",
    }
    for campo in (
        "cupoDiario",
        "cupoMensual",
        "montoMaxTransaccion",
        "consumidoHoy",
        "consumidoMes",
    ):
        assert efectivo[campo]["type"] == "number"
    assert esquemas["Cuenta"]["properties"]["idMoneda"]["const"] == 840


@pytest.mark.parametrize("index", [0, 2])
def test_cta_escrituras_rechazan_body_extra_http(sesion_cuentas, monkeypatch, index):

    usuario, dependencia = sesion_cuentas
    app.dependency_overrides[dependencia] = lambda: usuario
    method, path, body, _ = _RUTAS_NUEVAS[index]
    respuesta = asyncio.run(_http_cuentas(method, path, body | {"modificadoPor": 999}))
    assert respuesta.status_code == 400
    assert respuesta.json()["code"] == "DATOS_INVALIDOS"
    assert respuesta.json()["errors"][0]["field"] == "modificadoPor"


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "pageSize=0",
        "pageSize=101",
        "pageSize=abc",
        "page=1&page=2",
        "idCliente=125",
    ],
)
def test_cta09_validacion_http_de_paginacion_y_parametros(sesion_cuentas, query):
    usuario, dependencia = sesion_cuentas
    app.dependency_overrides[dependencia] = lambda: usuario
    respuesta = asyncio.run(
        _http_cuentas("GET", "/api/v1/cuentas/501/cupos/1/historial?" + query)
    )
    assert respuesta.status_code == 400
    assert respuesta.headers["content-type"].startswith("application/problem+json")


def test_cta09_convierte_datetime2_local_sin_inventar_columnas():
    db = _fake_conn(
        [_cuenta_bd_row()],
        [{"id_canal": 1}],
        [_historial_row(fecha_modificacion=datetime(2026, 11, 4, 15, 30))],
    )
    (item,) = service.obtener_historial_cupo(cast(Connection, db), 501, 1).items
    assert item.fecha_modificacion.isoformat() == "2026-11-04T15:30:00-05:00"


@pytest.mark.parametrize(
    "etapa", ["guardar_cupo_personalizado", "insertar_historial_cupo", "commit"]
)
def test_cta08_trigger_rollback_y_error_http_sanitizado(
    sesion_cuentas, monkeypatch, etapa
):

    usuario, dependencia = sesion_cuentas
    app.dependency_overrides[dependencia] = lambda: usuario
    # Restaurar solo el servicio: se conservan los dobles de auditoría y autenticación.
    monkeypatch.setattr(service, "actualizar_cupo", _actualizar_cupo_servicio)
    db = _db_actualizar_cupo()

    def fallar(*args, **kwargs):
        raise DBAPIError(
            "SQL_SECRETO",
            {"parametro": "DATO_PRIVADO"},
            Exception("42000", "mensaje privado (52003) (SQLExecDirectW)"),
        )

    monkeypatch.setattr(db if etapa == "commit" else repository, etapa, fallar)
    from app.core.database.db import cooperativa

    app.dependency_overrides[cooperativa] = lambda: db
    respuesta = asyncio.run(
        _http_cuentas("PUT", "/api/v1/cuentas/501/cupos/1", _CUPO_BODY)
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["code"] == "CUPO_SUPERA_MAXIMO_PRODUCTO"
    assert all(
        secreto not in respuesta.text
        for secreto in ("SQL_SECRETO", "DATO_PRIVADO", "mensaje privado")
    )
    assert db.commits == 0 and db.rollbacks == 1

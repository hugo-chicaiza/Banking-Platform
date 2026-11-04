import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast, get_args

import pytest
from fastapi import HTTPException
from fastapi.dependencies.utils import request_params_to_args
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy import Connection
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
    EstadoCuenta,
    SaldoCuenta,
)


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

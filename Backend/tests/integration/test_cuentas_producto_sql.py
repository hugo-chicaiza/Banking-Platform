"""E3-05 contra la CooperativaDB migrada; cada prueba corre en una transacción revertida."""

import os
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database.db import get_engine
from app.modules.contabilidad import cuentas_producto as cp

pytestmark = pytest.mark.skipif(
    not os.getenv("E305_SQL_DEV"), reason="Requiere la CooperativaDB con E3-05 aplicada"
)
HOY = date.today()


@pytest.fixture
def conn():
    with get_engine("cooperativa").connect() as c:
        tx = c.begin()
        yield c
        tx.rollback()


def _id(conn, sql: str, **p) -> int:
    return int(conn.execute(text(sql), p).scalar_one())


def _cuenta(conn, codigo: str) -> int:
    return _id(
        conn,
        "SELECT IdCuentaContable FROM Contabilidad.CuentasContables WHERE CodigoCuenta=:c",
        c=codigo,
    )


def _sub(conn, codigo: str) -> int:
    return _id(
        conn,
        "SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE CodigoSubProducto=:c",
        c=codigo,
    )


def _producto(conn, codigo: str) -> int:
    return _id(
        conn,
        "SELECT IdProducto FROM ProductosFinancieros.Producto WHERE CodigoProducto=:c",
        c=codigo,
    )


def _clase(conn, tipo: str, rol: str, **dim) -> int:
    filtro = " ".join(f"AND k.{k}=:{k}" for k in dim)
    return _id(
        conn,
        "SELECT k.IdClase FROM Contabilidad.ClaseCuentaProducto k JOIN ProductosFinancieros.TipoProducto t"
        f" ON t.IdTipoProducto=k.IdTipoProducto WHERE t.Codigo=:tipo AND k.CodigoRol=:rol {filtro}",
        tipo=tipo,
        rol=rol,
        **dim,
    )


def _tipo(conn, codigo: str) -> int:
    return _id(
        conn,
        "SELECT IdTipoProducto FROM ProductosFinancieros.TipoProducto WHERE Codigo=:c",
        c=codigo,
    )


def _error(fn) -> str:
    with pytest.raises(HTTPException) as e:
        fn()
    return e.value.detail["code"]  # type: ignore[index]


# AC 1: la cuenta debe ser hoja imputable dentro de la rama del rol
def test_cuenta_que_no_corresponde_es_rechazada(conn):
    cambio = cp.Cambio(
        id_clase=_clase(conn, "CUENTA_AHORRO", "CAPITAL"),
        id_producto=_producto(conn, "AHO003"),
        id_cuenta_contable=_cuenta(conn, "1402"),
        vigencia_desde=HOY + timedelta(days=1),
    )
    assert (
        _error(lambda: cp.validar(conn, _tipo(conn, "CUENTA_AHORRO"), cambio, HOY))
        == "CUENTA_NO_CORRESPONDE"
    )
    with pytest.raises(DBAPIError, match="CUENTA_NO_CORRESPONDE"):
        conn.execute(
            text(
                "INSERT Contabilidad.CuentaProducto(IdClase,IdProducto,IdCuentaContable,VigenciaDesde) VALUES(:k,:p,:c,:d)"
            ),
            {
                "k": cambio.id_clase,
                "p": cambio.id_producto,
                "c": _cuenta(conn, "210135"),
                "d": cambio.vigencia_desde,
            },
        )


# AC 2: sin CAPITAL no se activa
def test_sin_capital_hay_rol_faltante(conn):
    conn.execute(
        text(
            "UPDATE v SET Estado='I' FROM Contabilidad.CuentaProducto v JOIN Contabilidad.ClaseCuentaProducto k"
            " ON k.IdClase=v.IdClase WHERE k.CodigoRol='CAPITAL' AND v.IdProducto=:p"
        ),
        {"p": _producto(conn, "AHO002")},
    )
    assert "CAPITAL" in cp.roles_faltantes(conn, _sub(conn, "AHO002-JOV"), HOY)


# AC 3 y 6: el producto de ahorro tiene su auxiliar; sus subproductos lo heredan
def test_subproductos_heredan_el_capital_del_producto(conn):
    for codigo in ("AHO002-JOV", "AHO002-FAM", "AHO002-INF"):
        assert cp.cuenta_contable(conn, _sub(conn, codigo), "CAPITAL", HOY) == _cuenta(
            conn, "21013515"
        )
    assert cp.cuenta_contable(conn, _sub(conn, "AHO001-PJ"), "CAPITAL", HOY) == _cuenta(
        conn, "21013510"
    )
    assert cp.cuenta_contable(conn, _sub(conn, "AHO001-MN"), "CAPITAL", HOY) == _cuenta(
        conn, "21013505"
    )
    assert cp.roles_faltantes(conn, _sub(conn, "AHO002-FAM"), HOY) == []


# AC 4: el capital no se comparte entre productos
def test_capital_no_se_comparte(conn):
    cambio = cp.Cambio(
        id_clase=_clase(conn, "CUENTA_AHORRO", "CAPITAL"),
        id_producto=_producto(conn, "AHO003"),
        id_cuenta_contable=_cuenta(conn, "21013515"),
        vigencia_desde=HOY + timedelta(days=1),
    )
    assert (
        _error(lambda: cp.validar(conn, _tipo(conn, "CUENTA_AHORRO"), cambio, HOY))
        == "CUENTA_YA_ASIGNADA"
    )


# AC 5 (aplicación): la nueva asignación cierra la anterior el día previo
def test_aplicar_cierra_la_vigencia_anterior(conn):
    desde = HOY + timedelta(days=3)
    cambio = cp.Cambio(
        id_clase=_clase(conn, "CUENTA_AHORRO", "INTERES_GASTO"),
        id_cuenta_contable=_cuenta(conn, "410115"),
        vigencia_desde=desde,
    )
    cp.validar(conn, _tipo(conn, "CUENTA_AHORRO"), cambio, HOY)
    cp.aplicar_cambio(conn, cambio, 999999, None)
    filas = (
        conn.execute(
            text(
                "SELECT VigenciaDesde,VigenciaHasta FROM Contabilidad.CuentaProducto WHERE IdClase=:k AND IdProducto IS NULL AND IdSubProducto IS NULL AND Estado='A' ORDER BY VigenciaDesde"
            ),
            {"k": cambio.id_clase},
        )
        .mappings()
        .all()
    )
    assert filas[0]["VigenciaHasta"] == desde - timedelta(days=1)
    assert filas[1]["VigenciaDesde"] == desde and filas[1]["VigenciaHasta"] is None


def test_credito_y_tarjeta_de_credito_resuelven_por_tipo(conn):
    cre = _sub(conn, "CRE001-STD")
    assert cp.cuenta_contable(
        conn, cre, "CARTERA", HOY, situacion="POR_VENCER", tramo=1
    ) == _cuenta(conn, "140205")
    assert cp.cuenta_contable(
        conn, cre, "INTERES_GANADO", HOY, condicion="REFINANCIADA"
    ) == _cuenta(conn, "510430")
    micro = _sub(conn, "CRE002-STD")
    assert cp.cuenta_contable(
        conn, micro, "CARTERA", HOY, situacion="VENCIDA", tramo=5
    ) == _cuenta(conn, "145225")
    tcr = _sub(conn, "TCR001-MC")
    assert cp.cuenta_contable(
        conn, tcr, "CARTERA", HOY, situacion="POR_VENCER", tramo=2
    ) == _cuenta(conn, "140210")
    assert cp.cuenta_contable(conn, tcr, "CUPO_NO_UTILIZADO", HOY) == _cuenta(
        conn, "640410"
    )
    assert (
        _error(
            lambda: cp.cuenta_contable(conn, _sub(conn, "TDB001-MC"), "CAPITAL", HOY)
        )
        == "ROL_NO_APLICA"
    )


def test_comisiones_y_vinculos_respetan_la_norma(conn):
    ret = _id(
        conn,
        "SELECT IdComision FROM Transacciones.Comisiones WHERE CodigoComision='RET-ATM'",
    )
    conn.execute(
        text(
            "UPDATE Transacciones.ComisionValor SET VigenciaHasta=:h WHERE IdComision=:i AND VigenciaHasta IS NULL"
        ),
        {"i": ret, "h": HOY + timedelta(days=29)},
    )
    with pytest.raises(DBAPIError, match="COMISION_FUERA_DE_NORMA"):
        conn.execute(
            text(
                "INSERT Transacciones.ComisionValor(IdComision,Valor,VigenciaDesde) VALUES(:i,0.99,:d)"
            ),
            {"i": ret, "d": HOY + timedelta(days=30)},
        )
    with pytest.raises(DBAPIError, match="COMISION_NO_APLICA_CREDITO"):
        conn.execute(
            text(
                "INSERT ProductosFinancieros.ProductoComision(IdComision,IdSubProducto,Exonerado,Estado,AsignadoPor) VALUES(:i,:s,0,'A',8)"
            ),
            {"i": ret, "s": _sub(conn, "CRE002-STD")},
        )
    with pytest.raises(DBAPIError, match="SEGURO_SOLO_CREDITO"):
        conn.execute(
            text(
                "INSERT ProductosFinancieros.ProductoSeguro(IdSeguro,IdSubProducto,EsObligatorio,Estado,AsignadoPor) VALUES(1,:s,0,'A',8)"
            ),
            {"s": _sub(conn, "AHO003-PER")},
        )


# ---------- E3-06: lista de activación y retiro ----------


def test_activar_un_subproducto_incompleto_es_409(conn):
    from app.modules.productos import activacion

    with pytest.raises(HTTPException) as e:
        activacion.exigir_activacion(conn, _sub(conn, "AHO002-FAM"))
    assert e.value.status_code == 409
    assert e.value.detail["code"] == "ACTIVACION_INCOMPLETA"  # type: ignore[index]
    assert "numeración" in e.value.detail["message"]  # type: ignore[index]


def test_los_subproductos_activos_tienen_la_lista_completa(conn):
    from app.modules.productos import activacion

    activos = (
        conn.execute(
            text(
                "SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE EstadoSubProducto='Activo'"
            )
        )
        .scalars()
        .all()
    )
    assert activos
    for id_sub in activos:
        assert activacion.faltantes(conn, id_sub, HOY) == []


def test_retirar_con_cuentas_abiertas_es_409(conn):
    from app.modules.productos import activacion

    with pytest.raises(HTTPException) as e:
        activacion.exigir_retiro(conn, id_sub=_sub(conn, "AHO001-PN"))
    assert e.value.detail["code"] == "PRODUCTO_CON_CUENTAS"  # type: ignore[index]
    activacion.exigir_retiro(conn, id_sub=_sub(conn, "COR001-PN"))

"""Pruebas de integración para CTA-01 contra CooperativaDB.

Se omiten si la BD no está configurada (p. ej. en CI sin secretos).
Estos tests validan que las tablas y columnas referenciadas en el
repositorio existen y tienen la estructura esperada.

NO se realiza ningún INSERT definitivo: las pruebas usan ROLLBACK o
validan solo la existencia de filas de referencia.
"""

import pytest

from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.modules.cuentas import repository
from app.modules.cuentas.schemas import ID_MONEDA_USD

pytestmark = pytest.mark.skipif(
    not get_settings().cooperativa_db_server,
    reason="CooperativaDB no configurada",
)


@pytest.fixture(scope="module")
def conn():
    from sqlalchemy import event

    def solo_lectura(conn, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith(("SELECT ", "WITH "))

    def sin_commit(conn):
        raise AssertionError("Las integraciones de cuentas no deben hacer commit")

    with get_engine("cooperativa").connect() as c:
        event.listen(c, "before_cursor_execute", solo_lectura)
        event.listen(c, "commit", sin_commit)
        yield c


# ---------------------------------------------------------------------------
# Validar que las tablas/vistas tienen las columnas esperadas
# ---------------------------------------------------------------------------


def test_tabla_cliente_tiene_columnas(conn):
    """Clientes.Cliente debe tener IdCliente y Estado."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Clientes'
              AND TABLE_NAME   = 'Cliente'
              AND COLUMN_NAME IN ('IdCliente', 'Estado')
            """
        )
    ).scalar_one()
    assert row == 2, "Clientes.Cliente no tiene IdCliente o Estado"


def test_cta06_consulta_ledger_real_sin_modificar_saldos(conn):
    from datetime import date

    from sqlalchemy import text

    from app.modules.cuentas import service

    id_cuenta = conn.execute(
        text("""
                SELECT TOP 1 c.IdCuenta FROM Cuentas.Cuenta c
                WHERE EXISTS (SELECT 1 FROM Cuentas.MovimientoTransaccion m WHERE m.IdCuenta=c.IdCuenta)
                ORDER BY c.IdCuenta
            """)
    ).scalar_one_or_none()
    if id_cuenta is None:
        pytest.skip(
            "Se necesita una cuenta con movimientos para comprobar los saldos históricos"
        )
    desde, hasta = date(1900, 1, 1), date(9999, 12, 31)
    esperado = conn.execute(
        text("""
        SELECT TOP 20 m.IdMovimiento,m.SaldoAnterior,m.SaldoPosterior,m.FechaHoraSistema,
                      f.Fecha, t.IdCuenta, t.IdCuentaDestino
        FROM Cuentas.MovimientoTransaccion m
        JOIN Transacciones.Transaccion t ON t.IdTransaccion=m.IdTransaccion
        JOIN Contabilidad.FechaContable f ON f.IdFechaContable=m.IdFechaContable
        WHERE m.IdCuenta=:id
        ORDER BY m.FechaHoraSistema DESC,m.IdMovimiento DESC
    """),
        {"id": id_cuenta},
    ).all()
    total = conn.execute(
        text("SELECT COUNT(*) FROM Cuentas.MovimientoTransaccion WHERE IdCuenta=:id"),
        {"id": id_cuenta},
    ).scalar_one()
    resultado = service.listar_movimientos(conn, id_cuenta, desde=desde, hasta=hasta)
    assert resultado.total == total and total > 0
    assert [m.id_movimiento for m in resultado.items] == [fila[0] for fila in esperado]
    for movimiento, fila in zip(resultado.items, esperado, strict=True):
        assert movimiento.saldo_anterior == fila[1]
        assert movimiento.saldo_posterior == fila[2]
        assert movimiento.fecha_hora_sistema.replace(tzinfo=None) == fila[3]
        assert movimiento.fecha_contable == fila[4]
    vacia = service.listar_movimientos(
        conn, id_cuenta, desde=desde, hasta=hasta, page=1_000_000
    )
    assert vacia.items == [] and vacia.total == total


def test_tabla_riesgo_cliente_tiene_columnas(conn):
    """RiesgoCliente expone el resultado y la vigencia usados por CTA-01."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Clientes'
              AND TABLE_NAME   = 'RiesgoCliente'
              AND COLUMN_NAME IN (
                  'IdCliente', 'ResultadoEvaluacion', 'EsVigente'
              )
            """
        )
    ).scalar_one()
    assert row == 3, "Clientes.RiesgoCliente no tiene las columnas esperadas"


def test_tabla_producto_tiene_columnas(conn):
    """Producto aporta el tipo de cuenta usado por las lecturas de A-02."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'ProductosFinancieros'
              AND TABLE_NAME   = 'Producto'
              AND COLUMN_NAME IN (
                  'IdProducto', 'TipoProducto', 'Estado',
                  'MontoAperturaMinimo', 'TipoCuenta'
              )
            """
        )
    ).scalar_one()
    assert row == 5, "ProductosFinancieros.Producto no tiene las columnas esperadas"


def test_tabla_agencia_tiene_columna_estado(conn):
    """Organizacion.Agencia debe tener la clave usada por Cuenta y su Estado."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Organizacion'
              AND TABLE_NAME   = 'Agencia'
              AND COLUMN_NAME IN ('IdAgencia', 'Estado')
            """
        )
    ).scalar_one()
    assert row == 2, "Organizacion.Agencia no tiene IdAgencia o Estado"


def test_tabla_cuenta_tiene_columnas(conn):
    """Cuentas.Cuenta contiene los datos persistidos; moneda y tipo se derivan."""
    from sqlalchemy import text

    columnas = [
        "IdCuenta",
        "NumeroCuenta",
        "IdCliente",
        "IdProducto",
        "IdSubProducto",
        "IdAgencia",
        "Saldo",
        "SaldoRetenido",
        "Estado",
    ]
    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Cuentas'
              AND TABLE_NAME = 'Cuenta'
              AND COLUMN_NAME IN (
                  'IdCuenta', 'NumeroCuenta', 'IdCliente', 'IdProducto',
                  'IdSubProducto', 'IdAgencia', 'Saldo', 'SaldoRetenido', 'Estado'
              )
            """
        )
    ).scalar_one()
    assert row == len(columnas), (
        f"Cuentas.Cuenta no tiene todas las columnas esperadas ({row}/{len(columnas)})"
    )


def test_moneda_usd_es_regla_global_y_no_columna_de_cuenta(conn):
    """USD 840 pertenece al contrato, no se repite en cada fila de Cuenta."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'Cuentas'
              AND TABLE_NAME = 'Cuenta'
              AND COLUMN_NAME = 'IdMoneda'
            """
        )
    ).scalar_one()
    assert row == 0
    assert ID_MONEDA_USD == 840


def test_sp_abrir_cuenta_existe(conn):
    """Cuentas.usp_AbrirCuenta debe existir en la base de datos."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM sys.objects
            WHERE object_id = OBJECT_ID('Cuentas.usp_AbrirCuenta')
              AND type IN ('P', 'PC')
            """
        )
    ).scalar_one()
    assert row == 1, "Cuentas.usp_AbrirCuenta no existe"


def test_sp_abrir_cuenta_tiene_firma_esperada(conn):
    """La llamada del repositorio debe coincidir con los parámetros reales."""
    from sqlalchemy import text

    rows = conn.execute(
        text(
            """
            SELECT p.name
            FROM sys.parameters AS p
            WHERE p.object_id = OBJECT_ID('Cuentas.usp_AbrirCuenta')
            ORDER BY p.parameter_id
            """
        )
    ).scalars()
    assert list(rows) == [
        "@IdCliente",
        "@IdSubProducto",
        "@IdAgencia",
        "@NumeroCuenta",
        "@MontoInicial",
        "@CreadoPor",
        "@IdCuenta",
    ]


# ---------------------------------------------------------------------------
# Lectura real del repositorio (sin escribir nada)
# ---------------------------------------------------------------------------


def test_obtener_cliente_inexistente_devuelve_none(conn):
    result = repository.obtener_cliente(conn, id_cliente=-999)
    assert result is None


def test_obtener_agencia_inexistente_devuelve_none(conn):
    result = repository.obtener_agencia(conn, id_agencia="ZZZ")
    assert result is None


# CTA-05/07/08/09: toda esta sección usa SELECT, sin DML ni commits.
@pytest.mark.parametrize(
    "objeto,columnas",
    [
        (
            "Cuentas.Cuenta",
            {
                "IdCuenta",
                "IdProducto",
                "IdSubProducto",
                "Estado",
                "Saldo",
                "SaldoRetenido",
                "FechaCierre",
            },
        ),
        (
            "Credito.CreditoDesembolso",
            {"IdDesembolso", "IdSolicitud", "IdCuentaDesembolso", "Estado"},
        ),
        (
            "Canal.CanalCupoClienteCustom",
            {
                "IdCanalCupo",
                "IdCuenta",
                "IdCanal",
                "CupoDiario",
                "CupoMensual",
                "MontoMaxTransaccion",
                "MaxTransaccionesDia",
                "FechaVigencia",
                "Estado",
                "ModificadoPor",
            },
        ),
        (
            "ProductosFinancieros.ProductoCanalCupo",
            {
                "IdSubProducto",
                "IdCanal",
                "CupoDiarioMaximo",
                "CupoMensualMaximo",
                "MontoMaxTransaccion",
                "MaxTransaccionesDia",
            },
        ),
        (
            "Canal.CuposModHis",
            {
                "IdCupoModHis",
                "IdCanalCupoCliente",
                "CupoDiarioAnterior",
                "CupoDiarioNuevo",
                "CupoMensualAnterior",
                "CupoMensualNuevo",
                "MontoMaxTxAnterior",
                "MontoMaxTxNuevo",
                "ModificadoPor",
                "FechaModificacion",
            },
        ),
        (
            "Transacciones.Transaccion",
            {
                "IdCuenta",
                "IdCanal",
                "Monto",
                "Estado",
                "TipoOperacion",
                "TipoTransaccion",
                "FechaHoraSistema",
            },
        ),
        ("Transacciones.TipoTransaccion", {"CodigoTipo", "Naturaleza"}),
    ],
)
def test_cta_gestion_columnas_reales(conn, objeto, columnas):
    from sqlalchemy import text

    encontradas = set(
        conn.execute(
            text("SELECT name FROM sys.columns WHERE object_id=OBJECT_ID(:objeto)"),
            {"objeto": objeto},
        )
        .scalars()
        .all()
    )
    assert columnas <= encontradas
    if objeto == "Canal.CuposModHis":
        assert not {"IdCuenta", "IdCanal"} & encontradas


def test_cta_gestion_funcion_firma_y_semantica(conn):
    from sqlalchemy import text

    definicion = conn.execute(
        text("SELECT OBJECT_DEFINITION(OBJECT_ID('Canal.fn_CupoVigente'))")
    ).scalar_one()
    assert "p.IdSubProducto = c.IdSubProducto" in definicion
    assert "ProductosFinancieros.ProductoCanalCupo" in definicion
    assert "cc.FechaVigencia >= CAST" in definicion
    assert "cc.FechaVigencia IS NULL OR" in definicion
    assert "cc.Estado = 'A'" in definicion
    assert set(
        conn.execute(
            text(
                "SELECT name FROM sys.parameters WHERE object_id=OBJECT_ID('Canal.fn_CupoVigente')"
            )
        ).scalars()
    ) == {"@IdCuenta", "@IdCanal"}
    assert (
        conn.execute(text("SELECT OBJECT_ID('Canal.ProductoCanalCupo')")).scalar_one()
        is None
    )


def test_historial_cupos_conserva_esquema_original_tras_reversion(conn):
    from sqlalchemy import text

    columnas = set(
        conn.execute(
            text("""
        SELECT name FROM sys.columns WHERE object_id=OBJECT_ID('Canal.CuposModHis')
    """)
        ).scalars()
    )
    assert columnas == {
        "IdCupoModHis",
        "IdCanalCupoCliente",
        "CupoDiarioAnterior",
        "CupoDiarioNuevo",
        "CupoMensualAnterior",
        "CupoMensualNuevo",
        "MontoMaxTxAnterior",
        "MontoMaxTxNuevo",
        "ModificadoPor",
        "FechaModificacion",
    }


def test_cta_gestion_trigger_no_duplica_historial(conn):
    from sqlalchemy import text

    triggers = (
        conn.execute(
            text("""
        SELECT name,is_disabled,OBJECT_DEFINITION(object_id) AS definicion
        FROM sys.triggers WHERE parent_id=OBJECT_ID('Canal.CanalCupoClienteCustom')
    """)
        )
        .mappings()
        .all()
    )
    assert {t["name"] for t in triggers} == {"trg_CanalCupoClienteCustom_Tope"}
    assert all(not t["is_disabled"] for t in triggers)
    definicion = triggers[0]["definicion"]
    assert "THROW 52003" in definicion and "CuposModHis" not in definicion
    inmutable = conn.execute(
        text("SELECT OBJECT_DEFINITION(OBJECT_ID('Canal.trg_CuposModHis_Inmutable'))")
    ).scalar_one()
    assert "INSTEAD OF UPDATE, DELETE" in inmutable and "THROW 57001" in inmutable


def test_cta_gestion_claves_sin_ambiguedad(conn):
    from sqlalchemy import text

    filas = conn.execute(
        text("""
        SELECT OBJECT_SCHEMA_NAME(f.parent_object_id)+'.'+OBJECT_NAME(f.parent_object_id) origen,
               c.name columna, OBJECT_SCHEMA_NAME(f.referenced_object_id)+'.'+OBJECT_NAME(f.referenced_object_id) destino,
               r.name referencia
        FROM sys.foreign_key_columns f
        JOIN sys.columns c ON c.object_id=f.parent_object_id AND c.column_id=f.parent_column_id
        JOIN sys.columns r ON r.object_id=f.referenced_object_id AND r.column_id=f.referenced_column_id
    """)
    ).all()
    claves = {tuple(r) for r in filas}
    assert (
        "Canal.CuposModHis",
        "IdCanalCupoCliente",
        "Canal.CanalCupoClienteCustom",
        "IdCanalCupo",
    ) in claves
    assert (
        "Credito.CreditoDesembolso",
        "IdCuentaDesembolso",
        "Cuentas.Cuenta",
        "IdCuenta",
    ) in claves
    assert (
        "Cuentas.Cuenta",
        "IdSubProducto",
        "ProductosFinancieros.SubProducto",
        "IdSubProducto",
    ) in claves
    assert (
        "ProductosFinancieros.ProductoCanalCupo",
        "IdSubProducto",
        "ProductosFinancieros.SubProducto",
        "IdSubProducto",
    ) in claves


@pytest.mark.parametrize(
    "objeto,nombre,columnas,unico",
    [
        (
            "Canal.CanalCupoClienteCustom",
            "UQ_CanalCupoClienteCustom",
            ["IdCuenta", "IdCanal"],
            True,
        ),
        (
            "ProductosFinancieros.ProductoCanalCupo",
            "UQ_ProductoCanalCupo",
            ["IdSubProducto", "IdCanal"],
            True,
        ),
        ("Canal.CuposModHis", "PK_CuposModHis", ["IdCupoModHis"], True),
        (
            "Canal.CuposModHis",
            "IX_CuposModHis_CanalCupo",
            ["IdCanalCupoCliente", "FechaModificacion"],
            False,
        ),
        (
            "Transacciones.Transaccion",
            "IX_Transaccion_Cuenta_Fecha",
            ["IdCuenta", "IdFechaContable"],
            False,
        ),
    ],
)
def test_cta_gestion_indices(conn, objeto, nombre, columnas, unico):
    from sqlalchemy import text

    filas = conn.execute(
        text("""
        SELECT c.name,i.is_unique FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
        JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
        WHERE i.object_id=OBJECT_ID(:objeto) AND i.name=:nombre AND ic.key_ordinal>0
        ORDER BY ic.key_ordinal
    """),
        {"objeto": objeto, "nombre": nombre},
    ).all()
    assert [r[0] for r in filas] == columnas
    assert all(bool(r[1]) == unico for r in filas)


def test_cta_gestion_restricciones_y_reloj(conn):
    from sqlalchemy import text

    restricciones = dict(
        conn.execute(
            text("""
        SELECT name,definition FROM sys.check_constraints
        WHERE parent_object_id IN (OBJECT_ID('Cuentas.Cuenta'),OBJECT_ID('Canal.CanalCupoClienteCustom'),
            OBJECT_ID('Credito.CreditoDesembolso'),OBJECT_ID('Transacciones.Transaccion'),
            OBJECT_ID('ProductosFinancieros.ProductoCanalCupo'))
    """)
        ).all()
    )
    assert all(
        estado in restricciones["CK_Cuenta_Estado"]
        for estado in ("Activa", "Inactiva", "Bloqueada", "Cerrada")
    )
    assert "FechaCierre" in restricciones["CK_Cuenta_Cierre"]
    assert all(
        estado in restricciones["CK_CreditoDesembolso_Estado"]
        for estado in ("PENDIENTE", "DESEMBOLSADO", "REVERSADO")
    )
    # El contrato se adapta al CHECK vigente: cupos positivos, sin cambiar la base.
    cupos = restricciones["CK_CanalCupoClienteCustom_Cupos"].replace(" ", "")
    assert "[CupoDiario]>(0)" in cupos
    assert "[MontoMaxTransaccion]>(0)" in cupos
    assert "[CupoMensual]>=[CupoDiario]" in cupos
    assert "[MontoMaxTransaccion]<=[CupoDiario]" in cupos
    predeterminados = restricciones["CK_ProductoCanalCupo_Cupos"].replace(" ", "")
    assert "[CupoDiarioMaximo]>(0)" in predeterminados
    assert "[MontoMaxTransaccion]>(0)" in predeterminados
    assert "[CupoMensualMaximo]>=[CupoDiarioMaximo]" in predeterminados
    assert "[MontoMaxTransaccion]<=[CupoDiarioMaximo]" in predeterminados
    assert "Completada" in restricciones["CK_Transaccion_Estado"]
    for objeto in (
        "Canal.CanalCupoClienteCustom",
        "Canal.CuposModHis",
        "Transacciones.Transaccion",
    ):
        valores = (
            conn.execute(
                text(
                    "SELECT definition FROM sys.default_constraints WHERE parent_object_id=OBJECT_ID(:objeto)"
                ),
                {"objeto": objeto},
            )
            .scalars()
            .all()
        )
        assert any("AT TIME ZONE 'SA Pacific Standard Time'" in v for v in valores)


def test_cta07_y_cta09_sql_real_sin_escrituras(conn):
    from sqlalchemy import text

    from app.modules.cuentas import service

    assert repository.consultar_cupos_efectivos(conn, -2147483648) == []
    assert repository.consultar_historial_cupo(
        conn,
        -2147483648,
        -2147483648,
        page=1,
        page_size=20,
        campo="FechaModificacion",
        direccion="desc",
    ) == ([], 0)
    cuentas = (
        conn.execute(
            text("SELECT TOP (3) IdCuenta FROM Cuentas.Cuenta ORDER BY IdCuenta")
        )
        .scalars()
        .all()
    )
    for id_cuenta in cuentas:
        cupos = service.obtener_cupos(conn, id_cuenta)
        for cupo in cupos:
            directo = (
                conn.execute(
                    text("SELECT * FROM Canal.fn_CupoVigente(:cuenta,:canal)"),
                    {"cuenta": id_cuenta, "canal": cupo.id_canal},
                )
                .mappings()
                .one()
            )
            assert cupo.cupo_diario == directo["CupoDiario"]
            assert cupo.origen == (
                "Personalizado" if directo["Origen"] == "CUENTA" else "Producto"
            )
            consumos = conn.execute(
                text("""
                SELECT COALESCE(SUM(CASE WHEN CAST(t.FechaHoraSistema AS date)=h.hoy THEN t.Monto ELSE 0 END),0) diario,
                       COALESCE(SUM(t.Monto),0) mensual
                FROM Transacciones.Transaccion t
                JOIN Transacciones.TipoTransaccion tt ON tt.CodigoTipo=t.TipoTransaccion
                CROSS JOIN (SELECT CAST(SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time' AS date) hoy) h
                WHERE t.IdCuenta=:cuenta AND t.IdCanal=:canal AND t.Estado='Completada'
                  AND t.TipoOperacion='Normal' AND tt.Naturaleza='D'
                  AND t.FechaHoraSistema>=DATEFROMPARTS(YEAR(h.hoy),MONTH(h.hoy),1)
                  AND t.FechaHoraSistema<DATEADD(day,1,h.hoy)
            """),
                {"cuenta": id_cuenta, "canal": cupo.id_canal},
            ).one()
            assert (cupo.consumido_hoy, cupo.consumido_mes) == tuple(consumos)
            historial = service.obtener_historial_cupo(
                conn, id_cuenta, cupo.id_canal, page=100000
            )
            assert historial.items == []
            for campo in ("FechaModificacion", "IdCupoModHis"):
                for direccion in ("asc", "desc"):
                    repository.consultar_historial_cupo(
                        conn,
                        id_cuenta,
                        cupo.id_canal,
                        page=1,
                        page_size=2,
                        campo=campo,
                        direccion=direccion,
                    )


@pytest.mark.parametrize("fallar_historial", [False, True])
def test_cupo_e_historial_original_comparten_transaccion(monkeypatch, fallar_historial):
    from datetime import date

    from sqlalchemy import text

    from app.modules.cuentas import service
    from app.modules.cuentas.schemas import CupoUpdate
    from tests.sesion import ID_AUDITORIA

    # Esta prueba no usa la fixture de solo lectura. Toda escritura queda en una
    # transacción externa que se revierte, incluso si el servicio hace commit.
    with get_engine("cooperativa").connect() as conexion:
        try:
            referencia = conexion.execute(
                text("""
                SELECT TOP 1 c.IdCuenta,p.IdCanal,p.CupoDiarioMaximo,p.CupoMensualMaximo,
                             p.MontoMaxTransaccion
                FROM Cuentas.Cuenta c
                JOIN ProductosFinancieros.ProductoCanalCupo p ON p.IdSubProducto=c.IdSubProducto
                WHERE p.MaxTransaccionesDia >= 2
                ORDER BY c.IdCuenta,p.IdCanal
            """)
            ).one_or_none()
            if referencia is None:
                pytest.skip(
                    "Se necesita una cuenta con cupos configurados en su subproducto"
                )
            cuenta, canal = referencia[0], referencia[1]
            inicial = CupoUpdate.model_validate(
                {
                    "cupoDiario": referencia[2],
                    "cupoMensual": referencia[3],
                    "montoMaxTransaccion": referencia[4],
                    "maxTransaccionesDia": 1,
                    "fechaVigencia": date(2030, 1, 1),
                }
            )
            anterior = repository.bloquear_cupo_personalizado(conexion, cuenta, canal)
            repository.guardar_cupo_personalizado(
                conexion,
                cuenta,
                canal,
                inicial,
                ID_AUDITORIA,
                existe=anterior is not None,
            )
            savepoint = conexion.begin_nested()
            with monkeypatch.context() as cambios:
                cambios.setattr(conexion, "commit", savepoint.commit)
                cambios.setattr(conexion, "rollback", savepoint.rollback)
                if fallar_historial:

                    def fallar(*args, **kwargs):
                        raise RuntimeError("Historial no disponible")

                    cambios.setattr(repository, "insertar_historial_cupo", fallar)
                    with pytest.raises(RuntimeError):
                        service.actualizar_cupo(
                            conexion,
                            cuenta,
                            canal,
                            inicial.model_copy(
                                update={
                                    "fecha_vigencia": None,
                                    "max_transacciones_dia": 2,
                                }
                            ),
                            ID_AUDITORIA,
                        )
                else:
                    resultado = service.actualizar_cupo(
                        conexion,
                        cuenta,
                        canal,
                        inicial.model_copy(
                            update={"fecha_vigencia": None, "max_transacciones_dia": 2}
                        ),
                        ID_AUDITORIA,
                    )
                    assert resultado.fecha_vigencia is None
            actual = (
                conexion.execute(
                    text("""
                SELECT FechaVigencia AS fecha_vigencia,MaxTransaccionesDia AS max_transacciones_dia
                FROM Canal.CanalCupoClienteCustom WHERE IdCuenta=:cuenta AND IdCanal=:canal
            """),
                    {"cuenta": cuenta, "canal": canal},
                )
                .mappings()
                .one()
            )
            assert actual["fecha_vigencia"] == (
                date(2030, 1, 1) if fallar_historial else None
            )
            assert actual["max_transacciones_dia"] == (1 if fallar_historial else 2)
            if not fallar_historial:
                historial = service.obtener_historial_cupo(
                    conexion, cuenta, canal
                ).items[0]
                assert historial.cupo_diario_anterior == inicial.cupo_diario
                assert historial.cupo_diario_nuevo == inicial.cupo_diario
                assert historial.modificado_por == ID_AUDITORIA
        finally:
            conexion.rollback()

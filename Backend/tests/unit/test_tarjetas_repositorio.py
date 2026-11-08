"""SQL del repositorio de tarjetas para el ciclo de vida de A-05 (sin BD)."""

from datetime import date
from unittest.mock import MagicMock

from app.modules.tarjetas import repository


def test_actualizar_estado_sql_fijo_con_marcas_como_parametros():
    conn = MagicMock()
    repository.actualizar_estado(conn, 301, "Generada")
    sql, params = conn.execute.call_args.args
    assert params == {
        "estado": "Generada",
        "id_tarjeta": 301,
        "resolucion": 0,
        "emision": 0,
        "pin_asignado": 0,
    }

    repository.actualizar_estado(
        conn, 301, "Aprobada", resolucion=True, emision=True, pin_asignado=True
    )
    sql2, params = conn.execute.call_args.args
    assert str(sql2) == str(sql)  # el texto SQL nunca cambia
    assert params["resolucion"] == params["emision"] == params["pin_asignado"] == 1
    assert "FechaExpiracion = CASE WHEN :emision = 1" in str(sql)


def test_emision_inserta_solicitada_con_fecha_de_solicitud():
    conn = MagicMock()
    repository.insertar_tarjeta(conn, {})
    sql = str(conn.execute.call_args.args[0])
    assert "FechaSolicitud" in sql and "'Solicitada'" in sql
    assert "'Generada'" not in sql


def test_guardar_pin_generado_actualiza_o_inserta_habilitado():
    conn = MagicMock()
    conn.execute.return_value.rowcount = 1
    repository.guardar_pin_generado(conn, 301, "0042", "SIM-PVK-01", True)
    sql, params = conn.execute.call_args.args
    assert conn.execute.call_count == 1
    assert "Estado = 'Activo'" in str(sql) and "IntentosFallidos = 0" in str(sql)
    assert "FechaBloqueo = NULL" in str(sql)
    assert params == {
        "id_tarjeta": 301,
        "offset": "0042",
        "pvk": "SIM-PVK-01",
        "requiere_cambio": True,
    }

    conn = MagicMock()
    conn.execute.return_value.rowcount = 0
    repository.guardar_pin_generado(conn, 301, "0042", "SIM-PVK-01", False)
    assert conn.execute.call_count == 2
    assert "INSERT INTO Tarjetas.TarjetaPIN" in str(conn.execute.call_args.args[0])


def test_dias_laborables_usa_el_calendario_contable():
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = 3
    assert repository.dias_laborables_desde(conn, date(2026, 11, 4)) == 3
    sql, params = conn.execute.call_args.args
    assert "Contabilidad.FechaContable" in str(sql)
    assert "EsDiaContable = 1" in str(sql) and "Fecha > :fecha" in str(sql)
    assert params == {"fecha": date(2026, 11, 4)}

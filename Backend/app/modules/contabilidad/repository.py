from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text


def _one(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    fila = conn.execute(text(sql), params or {}).mappings().first()
    return dict(fila) if fila else None


def obtener_por_fecha(conn: Connection, fecha: date) -> dict[str, Any] | None:
    """Fila del calendario contable de un día calendario, o None si no está cargado."""
    return _one(
        conn,
        """
        SELECT IdFechaContable AS id_fecha_contable,
               Fecha           AS fecha,
               EsDiaContable   AS es_dia_contable,
               EsFeriado       AS es_feriado,
               EsFinDeSemana   AS es_fin_de_semana,
               HoraCorte       AS hora_corte
        FROM Contabilidad.FechaContable
        WHERE Fecha = :fecha
        """,
        {"fecha": fecha},
    )


def obtener_por_id(conn: Connection, id_fecha_contable: int) -> dict[str, Any] | None:
    """Fila del calendario contable por su IdFechaContable, o None si no existe."""
    return _one(
        conn,
        """
        SELECT IdFechaContable AS id_fecha_contable,
               Fecha           AS fecha,
               EsDiaContable   AS es_dia_contable,
               EsFeriado       AS es_feriado,
               EsFinDeSemana   AS es_fin_de_semana,
               HoraCorte       AS hora_corte
        FROM Contabilidad.FechaContable
        WHERE IdFechaContable = :id_fecha_contable
        """,
        {"id_fecha_contable": id_fecha_contable},
    )


def id_fecha_contable(conn: Connection, fecha_hora: datetime) -> int | None:
    """IdFechaContable de una operación, según Contabilidad.fn_IdFechaContable.

    La regla (corte 19:00, fines de semana, feriados) vive en la función de la DB
    y NO se reimplementa aquí. Devuelve None si el calendario no cubre la fecha.
    """
    fila = _one(
        conn,
        """
        SELECT Contabilidad.fn_IdFechaContable(CAST(:fecha_hora AS datetime2))
               AS id_fecha_contable
        """,
        {"fecha_hora": fecha_hora},
    )
    return fila["id_fecha_contable"] if fila else None

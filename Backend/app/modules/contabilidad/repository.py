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


def listar_cuentas_contables(
    conn: Connection, q: str | None, imputable: bool | None
) -> list[dict[str, Any]]:
    """Plan de cuentas (CON-03) ordenado por código; filtros opcionales.

    `q` busca por código o nombre (sin distinguir mayúsculas; % y _ se toman
    literales). TipoCuenta es una columna calculada de CuentasContables a partir
    de Contabilidad.ElementoCUC, por eso no hace falta el JOIN.
    """
    sql = """
        SELECT IdCuentaContable AS id_cuenta_contable,
               CodigoCuenta     AS codigo_cuenta,
               NombreCuenta     AS nombre_cuenta,
               Naturaleza       AS naturaleza,
               TipoCuenta       AS tipo_cuenta,
               IdCuentaSuperior AS id_cuenta_superior,
               EsImputable      AS es_imputable,
               Saldo            AS saldo,
               Estado           AS estado
        FROM Contabilidad.CuentasContables
        WHERE 1 = 1
    """
    params: dict[str, Any] = {}
    if q is not None:
        sql += """
          AND (CodigoCuenta LIKE :patron ESCAPE '\\'
               OR NombreCuenta LIKE :patron ESCAPE '\\')
        """
        escapado = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["patron"] = f"%{escapado}%"
    if imputable is not None:
        sql += " AND EsImputable = :imputable"
        params["imputable"] = 1 if imputable else 0
    sql += " ORDER BY CodigoCuenta"
    return [dict(f) for f in conn.execute(text(sql), params).mappings().all()]

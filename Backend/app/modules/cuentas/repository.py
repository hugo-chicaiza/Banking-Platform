from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.modules.cuentas.schemas import CupoUpdate

_ESTADOS_CUENTA_BD = {
    "ACTIVA": "Activa",
    "INACTIVA": "Inactiva",
    "BLOQUEADA": "Bloqueada",
    "CERRADA": "Cerrada",
}
_ESTADOS_CUENTA_API = {valor: clave for clave, valor in _ESTADOS_CUENTA_BD.items()}


def _cuenta_desde_bd(fila: dict[str, Any]) -> dict[str, Any]:
    """Adapta los estados verificados sin alterar el contrato ni la fila leída."""
    return {
        **fila,
        "estado": _ESTADOS_CUENTA_API.get(fila["estado"], fila["estado"]),
    }


def _rows(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]


def _one(
    conn: Connection, sql: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


def consultar_cuentas(
    conn: Connection,
    *,
    id_cliente: int | None = None,
    numero_cuenta: str | None = None,
    estado: str | None = None,
    id_agencia: str | None = None,
    page: int = 1,
    page_size: int = 20,
    campo: str = "IdCuenta",
    direccion: str = "asc",
) -> tuple[list[dict[str, Any]], int]:
    """Una lectura conserva el total incluso cuando la página está vacía."""
    filas = _rows(
        conn,
        """
        WITH Filtrados AS (
            SELECT c.IdCuenta AS id_cuenta, c.NumeroCuenta AS numero_cuenta,
                   c.IdCliente AS id_cliente, c.IdProducto AS id_producto,
                   c.IdAgencia AS id_agencia, p.TipoCuenta AS tipo_cuenta,
                   c.Estado AS estado,
                   ROW_NUMBER() OVER (ORDER BY
                       CASE WHEN :campo = 'IdCuenta' AND :direccion = 'asc'
                            THEN c.IdCuenta END ASC,
                       CASE WHEN :campo = 'IdCuenta' AND :direccion = 'desc'
                            THEN c.IdCuenta END DESC,
                       CASE WHEN :campo = 'NumeroCuenta' AND :direccion = 'asc'
                            THEN c.NumeroCuenta END ASC,
                       CASE WHEN :campo = 'NumeroCuenta' AND :direccion = 'desc'
                            THEN c.NumeroCuenta END DESC,
                       CASE WHEN :campo = 'IdCliente' AND :direccion = 'asc'
                            THEN c.IdCliente END ASC,
                       CASE WHEN :campo = 'IdCliente' AND :direccion = 'desc'
                            THEN c.IdCliente END DESC,
                       CASE WHEN :campo = 'IdProducto' AND :direccion = 'asc'
                            THEN c.IdProducto END ASC,
                       CASE WHEN :campo = 'IdProducto' AND :direccion = 'desc'
                            THEN c.IdProducto END DESC,
                       CASE WHEN :campo = 'IdAgencia' AND :direccion = 'asc'
                            THEN c.IdAgencia END ASC,
                       CASE WHEN :campo = 'IdAgencia' AND :direccion = 'desc'
                            THEN c.IdAgencia END DESC,
                       CASE WHEN :campo = 'TipoCuenta' AND :direccion = 'asc'
                            THEN p.TipoCuenta END ASC,
                       CASE WHEN :campo = 'TipoCuenta' AND :direccion = 'desc'
                            THEN p.TipoCuenta END DESC,
                       CASE WHEN :campo = 'Estado' AND :direccion = 'asc'
                            THEN c.Estado END ASC,
                       CASE WHEN :campo = 'Estado' AND :direccion = 'desc'
                            THEN c.Estado END DESC,
                       c.IdCuenta ASC
                   ) AS numero_fila
            FROM Cuentas.Cuenta AS c
            INNER JOIN ProductosFinancieros.Producto AS p
              ON p.IdProducto = c.IdProducto
            WHERE (:id_cliente IS NULL OR c.IdCliente = :id_cliente)
              AND (:numero_cuenta IS NULL OR c.NumeroCuenta = :numero_cuenta)
              AND (:estado IS NULL OR c.Estado = :estado)
              AND (:id_agencia IS NULL OR c.IdAgencia = :id_agencia)
        )
        SELECT p.*, t.total
        FROM (SELECT COUNT(*) AS total FROM Filtrados) AS t
        LEFT JOIN Filtrados AS p
          ON p.numero_fila > :offset AND p.numero_fila <= :limite
        ORDER BY p.numero_fila
        """,
        {
            "id_cliente": id_cliente,
            "numero_cuenta": numero_cuenta,
            "estado": _ESTADOS_CUENTA_BD.get(estado, estado)
            if estado is not None
            else None,
            "id_agencia": id_agencia,
            "campo": campo,
            "direccion": direccion,
            "offset": (page - 1) * page_size,
            "limite": page * page_size,
        },
    )
    total = int(filas[0]["total"]) if filas else 0
    return [
        _cuenta_desde_bd(fila) for fila in filas if fila["id_cuenta"] is not None
    ], total


def obtener_cuenta_por_id(conn: Connection, id_cuenta: int) -> dict[str, Any] | None:
    """Lee la cuenta; la moneda global USD se completa en el servicio."""
    fila = _one(
        conn,
        """
        SELECT c.IdCuenta AS id_cuenta, c.NumeroCuenta AS numero_cuenta,
               c.IdCliente AS id_cliente, c.IdProducto AS id_producto,
               c.IdAgencia AS id_agencia, p.TipoCuenta AS tipo_cuenta,
               c.Saldo AS saldo, c.SaldoRetenido AS saldo_retenido,
               c.Estado AS estado
        FROM Cuentas.Cuenta AS c
        INNER JOIN ProductosFinancieros.Producto AS p
          ON p.IdProducto = c.IdProducto
        WHERE c.IdCuenta = :id_cuenta
        """,
        {"id_cuenta": id_cuenta},
    )
    return _cuenta_desde_bd(fila) if fila is not None else None


# Validar cliente, riesgo, producto y agencia.


def obtener_cliente(conn: Connection, id_cliente: int) -> dict[str, Any] | None:
    """Devuelve {estado} del cliente o None si no existe."""
    return _one(
        conn,
        """
        SELECT Estado AS estado
        FROM Clientes.Cliente
        WHERE IdCliente = :id_cliente
        """,
        {"id_cliente": id_cliente},
    )


def obtener_riesgo_vigente(conn: Connection, id_cliente: int) -> dict[str, Any] | None:
    """Devuelve el riesgo vigente más reciente del cliente.

    Columnas: estado ('Aprobado' | 'Rechazado' | ...).
    """
    return _one(
        conn,
        """
        SELECT TOP 1 ResultadoEvaluacion AS estado
        FROM Clientes.RiesgoCliente
        WHERE IdCliente = :id_cliente
          AND EsVigente = 1
        ORDER BY FechaEvaluacion DESC
        """,
        {"id_cliente": id_cliente},
    )


def obtener_subproducto(conn: Connection, id_subproducto: int) -> dict[str, Any] | None:
    """Devuelve el subproducto y su producto padre para validar CTA-01."""
    return _one(
        conn,
        """
        SELECT s.IdSubProducto AS id_subproducto,
               s.IdProducto AS id_producto,
               s.Estado AS estado_subproducto,
               p.TipoProducto AS tipo_producto,
               p.TipoCuenta AS tipo_cuenta,
               p.Estado AS estado_producto,
               p.MontoAperturaMinimo AS monto_apertura_minimo
        FROM ProductosFinancieros.SubProducto AS s
        INNER JOIN ProductosFinancieros.Producto AS p
          ON p.IdProducto = s.IdProducto
        WHERE s.IdSubProducto = :id_subproducto
        """,
        {"id_subproducto": id_subproducto},
    )


def obtener_agencia(conn: Connection, id_agencia: str) -> dict[str, Any] | None:
    """Devuelve {estado} de la agencia o None si no existe."""
    return _one(
        conn,
        """
        SELECT Estado AS estado
        FROM Organizacion.Agencia
        WHERE IdAgencia = :id_agencia
        """,
        {"id_agencia": id_agencia},
    )


# Apertura de la cuenta


def abrir_cuenta(
    conn: Connection,
    numero_cuenta: str,
    id_cliente: int,
    id_subproducto: int,
    id_agencia: str,
    monto_inicial: Decimal,
    creado_por: int,
) -> dict[str, Any]:
    """Ejecuta la firma real del SP y lee la cuenta por su id de salida."""
    salida = _one(
        conn,
        """
        DECLARE @id_cuenta int;
        EXEC Cuentas.usp_AbrirCuenta
            @IdCliente       = :id_cliente,
            @IdSubProducto   = :id_subproducto,
            @IdAgencia       = :id_agencia,
            @NumeroCuenta    = :numero_cuenta,
            @MontoInicial    = :monto_inicial,
            @CreadoPor       = :creado_por,
            @IdCuenta        = @id_cuenta OUTPUT;
        SELECT @id_cuenta AS id_cuenta;
        """,
        {
            "id_cliente": id_cliente,
            "id_subproducto": id_subproducto,
            "id_agencia": id_agencia,
            "numero_cuenta": numero_cuenta,
            "monto_inicial": monto_inicial,
            "creado_por": creado_por,
        },
    )
    cuenta = (
        obtener_cuenta_por_id(conn, int(salida["id_cuenta"]))
        if salida is not None and salida["id_cuenta"] is not None
        else None
    )
    if cuenta is None:  # pragma: no cover
        raise RuntimeError("usp_AbrirCuenta no devolvió la cuenta creada")

    return cuenta


# CTA-05: XLOCK protege estado/saldos y la clave referenciada por los desembolsos.
def bloquear_cuenta(conn: Connection, id_cuenta: int) -> dict[str, Any] | None:
    fila = _one(
        conn,
        """
        SELECT IdCuenta AS id_cuenta, Estado AS estado,
               Saldo AS saldo, SaldoRetenido AS saldo_retenido
        FROM Cuentas.Cuenta WITH (XLOCK, HOLDLOCK)
        WHERE IdCuenta = :id_cuenta
        """,
        {"id_cuenta": id_cuenta},
    )
    return _cuenta_desde_bd(fila) if fila is not None else None


def desembolsos_de_cuenta(conn: Connection, id_cuenta: int) -> list[dict[str, Any]]:
    # HOLDLOCK protege también la ausencia de filas y evita nuevos vínculos durante el cierre.
    return _rows(
        conn,
        """
        SELECT IdSolicitud AS id_solicitud, Estado AS estado
        FROM Credito.CreditoDesembolso WITH (UPDLOCK, HOLDLOCK)
        WHERE IdCuentaDesembolso = :id_cuenta
        ORDER BY IdSolicitud, IdDesembolso
        """,
        {"id_cuenta": id_cuenta},
    )


def actualizar_estado_cuenta(conn: Connection, id_cuenta: int, estado: str) -> None:
    conn.execute(
        text("""
        UPDATE Cuentas.Cuenta
        SET Estado = :estado,
            FechaCierre = CASE WHEN :estado = 'Cerrada' THEN
                CONVERT(datetime2, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time')
                ELSE FechaCierre END
        WHERE IdCuenta = :id_cuenta
        """),
        {"id_cuenta": id_cuenta, "estado": _ESTADOS_CUENTA_BD[estado]},
    )


# CTA-07/08: una sola proyección y una sola función de BD deciden el cupo efectivo.
def consultar_cupos_efectivos(
    conn: Connection, id_cuenta: int, id_canal: int | None = None
) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        WITH Reloj AS (
            SELECT CONVERT(date, SYSDATETIMEOFFSET()
                AT TIME ZONE 'SA Pacific Standard Time') AS hoy
        ), Limites AS (
            SELECT hoy, DATEFROMPARTS(YEAR(hoy), MONTH(hoy), 1) AS inicio_mes,
                   DATEADD(day, 1, hoy) AS manana
            FROM Reloj
        ), Consumo AS (
            SELECT t.IdCanal,
                   SUM(CASE WHEN t.FechaHoraSistema >= l.hoy THEN t.Monto ELSE 0 END)
                       AS consumido_hoy,
                   SUM(t.Monto) AS consumido_mes
            FROM Transacciones.Transaccion AS t
            JOIN Transacciones.TipoTransaccion AS tt ON tt.CodigoTipo = t.TipoTransaccion
            CROSS JOIN Limites AS l
            WHERE t.IdCuenta = :id_cuenta
              AND (:id_canal IS NULL OR t.IdCanal = :id_canal)
              AND t.Estado = 'Completada' AND t.TipoOperacion = 'Normal'
              AND tt.Naturaleza = 'D'
              AND t.FechaHoraSistema >= l.inicio_mes AND t.FechaHoraSistema < l.manana
            GROUP BY t.IdCanal
        )
        SELECT canal.IdCanal AS id_canal,
               CASE WHEN v.Origen = 'CUENTA' THEN 'Personalizado' ELSE 'Producto' END AS origen,
               v.CupoDiario AS cupo_diario, v.CupoMensual AS cupo_mensual,
               v.MontoMaxTransaccion AS monto_max_transaccion,
               v.MaxTransaccionesDia AS max_transacciones_dia,
               CASE WHEN v.Origen = 'CUENTA' THEN cc.FechaVigencia END AS fecha_vigencia,
               COALESCE(cons.consumido_hoy, 0) AS consumido_hoy,
               COALESCE(cons.consumido_mes, 0) AS consumido_mes
        FROM Canal.Canal AS canal
        CROSS APPLY Canal.fn_CupoVigente(:id_cuenta, canal.IdCanal) AS v
        LEFT JOIN Canal.CanalCupoClienteCustom AS cc
          ON cc.IdCuenta = :id_cuenta AND cc.IdCanal = canal.IdCanal
        LEFT JOIN Consumo AS cons ON cons.IdCanal = canal.IdCanal
        WHERE (:id_canal IS NULL OR canal.IdCanal = :id_canal)
        ORDER BY canal.IdCanal
        """,
        {"id_cuenta": id_cuenta, "id_canal": id_canal},
    )


def obtener_canal(conn: Connection, id_canal: int) -> dict[str, Any] | None:
    return _one(
        conn,
        "SELECT IdCanal AS id_canal FROM Canal.Canal WHERE IdCanal = :id_canal",
        {"id_canal": id_canal},
    )


def bloquear_cupo_producto(
    conn: Connection, id_cuenta: int, id_canal: int
) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT p.CupoDiarioMaximo AS cupo_diario, p.CupoMensualMaximo AS cupo_mensual,
               p.MontoMaxTransaccion AS monto_max_transaccion,
               p.MaxTransaccionesDia AS max_transacciones_dia
        FROM Cuentas.Cuenta AS c
        JOIN ProductosFinancieros.ProductoCanalCupo AS p WITH (HOLDLOCK)
          ON p.IdSubProducto = c.IdSubProducto AND p.IdCanal = :id_canal
        WHERE c.IdCuenta = :id_cuenta
        """,
        {"id_cuenta": id_cuenta, "id_canal": id_canal},
    )


def bloquear_cupo_personalizado(
    conn: Connection, id_cuenta: int, id_canal: int
) -> dict[str, Any] | None:
    return _one(
        conn,
        """
        SELECT IdCanalCupo AS id_canal_cupo, CupoDiario AS cupo_diario,
               CupoMensual AS cupo_mensual, MontoMaxTransaccion AS monto_max_transaccion
        FROM Canal.CanalCupoClienteCustom WITH (UPDLOCK, HOLDLOCK)
        WHERE IdCuenta = :id_cuenta AND IdCanal = :id_canal
        """,
        {"id_cuenta": id_cuenta, "id_canal": id_canal},
    )


def guardar_cupo_personalizado(
    conn: Connection,
    id_cuenta: int,
    id_canal: int,
    payload: CupoUpdate,
    modificado_por: int,
    *,
    existe: bool,
) -> None:
    params = {
        **payload.model_dump(),
        "id_cuenta": id_cuenta,
        "id_canal": id_canal,
        "modificado_por": modificado_por,
    }
    if existe:
        sql = """
        UPDATE Canal.CanalCupoClienteCustom
        SET CupoDiario = :cupo_diario, CupoMensual = :cupo_mensual,
            MontoMaxTransaccion = :monto_max_transaccion,
            MaxTransaccionesDia = :max_transacciones_dia,
            FechaVigencia = :fecha_vigencia, Estado = 'A', ModificadoPor = :modificado_por
        WHERE IdCuenta = :id_cuenta AND IdCanal = :id_canal
        """
    else:
        sql = """
        INSERT INTO Canal.CanalCupoClienteCustom (
            IdCuenta, IdCanal, CupoDiario, CupoMensual, MontoMaxTransaccion,
            MaxTransaccionesDia, FechaVigencia, Estado, ModificadoPor
        ) VALUES (
            :id_cuenta, :id_canal, :cupo_diario, :cupo_mensual, :monto_max_transaccion,
            :max_transacciones_dia, :fecha_vigencia, 'A', :modificado_por
        )
        """
    conn.execute(text(sql), params)


def insertar_historial_cupo(
    conn: Connection,
    id_cuenta: int,
    id_canal: int,
    anterior: dict[str, Any] | None,
    payload: CupoUpdate,
    modificado_por: int,
) -> None:
    # El único trigger de Custom valida topes; NO inserta CuposModHis.
    previo = anterior or {}
    conn.execute(
        text("""
        INSERT INTO Canal.CuposModHis (
            IdCanalCupoCliente, CupoDiarioAnterior, CupoDiarioNuevo,
            CupoMensualAnterior, CupoMensualNuevo, MontoMaxTxAnterior,
            MontoMaxTxNuevo, ModificadoPor
        )
        SELECT IdCanalCupo, :diario_anterior, :cupo_diario,
               :mensual_anterior, :cupo_mensual, :max_anterior,
               :monto_max_transaccion, :modificado_por
        FROM Canal.CanalCupoClienteCustom
        WHERE IdCuenta = :id_cuenta AND IdCanal = :id_canal
        """),
        {
            **payload.model_dump(),
            "id_cuenta": id_cuenta,
            "id_canal": id_canal,
            "diario_anterior": previo.get("cupo_diario"),
            "mensual_anterior": previo.get("cupo_mensual"),
            "max_anterior": previo.get("monto_max_transaccion"),
            "modificado_por": modificado_por,
        },
    )


def consultar_historial_cupo(
    conn: Connection,
    id_cuenta: int,
    id_canal: int,
    *,
    page: int,
    page_size: int,
    campo: str,
    direccion: str,
) -> tuple[list[dict[str, Any]], int]:
    filas = _rows(
        conn,
        """
        WITH Historial AS (
            SELECT h.IdCupoModHis AS id_cupo_mod_his,
                   h.CupoDiarioAnterior AS cupo_diario_anterior,
                   h.CupoDiarioNuevo AS cupo_diario_nuevo,
                   h.CupoMensualAnterior AS cupo_mensual_anterior,
                   h.CupoMensualNuevo AS cupo_mensual_nuevo,
                   h.MontoMaxTxAnterior AS monto_max_tx_anterior,
                   h.MontoMaxTxNuevo AS monto_max_tx_nuevo,
                   h.ModificadoPor AS modificado_por,
                   h.FechaModificacion AS fecha_modificacion,
                   ROW_NUMBER() OVER (ORDER BY
                     CASE WHEN :campo = 'FechaModificacion' AND :direccion = 'asc'
                          THEN h.FechaModificacion END ASC,
                     CASE WHEN :campo = 'FechaModificacion' AND :direccion = 'desc'
                          THEN h.FechaModificacion END DESC,
                     CASE WHEN :campo = 'IdCupoModHis' AND :direccion = 'asc'
                          THEN h.IdCupoModHis END ASC,
                     CASE WHEN :campo = 'IdCupoModHis' AND :direccion = 'desc'
                          THEN h.IdCupoModHis END DESC,
                     h.IdCupoModHis DESC
                   ) AS numero_fila
            FROM Canal.CuposModHis AS h
            JOIN Canal.CanalCupoClienteCustom AS cc ON cc.IdCanalCupo = h.IdCanalCupoCliente
            WHERE cc.IdCuenta = :id_cuenta AND cc.IdCanal = :id_canal
        )
        SELECT p.*, t.total
        FROM (SELECT COUNT(*) AS total FROM Historial) AS t
        LEFT JOIN Historial AS p ON p.numero_fila > :offset AND p.numero_fila <= :limite
        ORDER BY p.numero_fila
        """,
        {
            "id_cuenta": id_cuenta,
            "id_canal": id_canal,
            "campo": campo,
            "direccion": direccion,
            "offset": (page - 1) * page_size,
            "limite": page * page_size,
        },
    )
    total = int(filas[0]["total"]) if filas else 0
    return [f for f in filas if f["id_cupo_mod_his"] is not None], total

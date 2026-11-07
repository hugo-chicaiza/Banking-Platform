"""SQL de Transacciones. Solo consultas parametrizadas con fragmentos fijos."""

from typing import Any

from sqlalchemy import Connection, text

from app.core.database.procedimientos import ejecutar_con_salidas

Fila = dict[str, Any]

_COLUMNAS = """
t.IdTransaccion, t.NumeroComprobante, t.RegistroUnico, t.MTI, t.STAN, t.RRN,
t.TipoOperacion, t.TipoTransaccion, t.IdCuenta, t.IdCuentaDestino, t.IdTarjeta,
t.IdCanal, t.IdATM AS IdTerminal, t.IdAgencia, t.IdJornadaCaja,
t.IdTransaccionRelacionada, t.Monto, t.CodigoRespuesta, t.Estado,
t.IdFechaContable, t.FechaHoraSistema, t.CreadoPor, t.NumeroAutorizacion,
COALESCE(t.IdAgencia, c.IdAgencia) AS AgenciaOperacion
"""
_ORIGEN = """
FROM Transacciones.Transaccion t
JOIN Cuentas.Cuenta c ON c.IdCuenta = t.IdCuenta
"""

# --- TRX-01 consulta -----------------------------------------------------------------

_FILTROS = {
    "id_cuenta": " AND t.IdCuenta = :id_cuenta",
    "tipo_transaccion": " AND t.TipoTransaccion = :tipo_transaccion",
    "estado": " AND t.Estado = :estado",
    "id_canal": " AND t.IdCanal = :id_canal",
    "id_agencia": " AND t.IdAgencia = :id_agencia",
    "desde": " AND t.FechaHoraSistema >= :desde",
    "hasta": " AND t.FechaHoraSistema < :hasta",
    # SUPERVISOR: solo su agencia (de la transacción o, si no tiene, de la cuenta)
    "alcance": " AND COALESCE(t.IdAgencia, c.IdAgencia) = :alcance",
}
ORDEN = {
    "fechaHoraSistema": "t.FechaHoraSistema",
    "monto": "t.Monto",
    "idTransaccion": "t.IdTransaccion",
}


def listar_transacciones(
    conn: Connection,
    filtros: dict[str, Any],
    orden: tuple[str, str],
    offset: int,
    limite: int,
) -> tuple[list[Fila], int]:
    parametros = {k: v for k, v in filtros.items() if v is not None}
    where = " WHERE 1 = 1" + "".join(_FILTROS[k] for k in parametros)
    columna = ORDEN[orden[0]]
    direccion = "DESC" if orden[1] == "desc" else "ASC"
    total = conn.execute(
        text("SELECT COUNT_BIG(*)" + _ORIGEN + where),  # fijo
        parametros,
    ).scalar_one()
    filas = conn.execute(
        text(
            "SELECT"  # fragmentos fijos de este módulo
            + _COLUMNAS
            + _ORIGEN
            + where
            + f" ORDER BY {columna} {direccion}, t.IdTransaccion {direccion}"
            + " OFFSET :offset ROWS FETCH NEXT :limite ROWS ONLY"
        ),
        {**parametros, "offset": offset, "limite": limite},
    ).mappings()
    return [dict(fila) for fila in filas], int(total)


# --- TRX-02: detalle de transacción ----------


def obtener_transaccion(
    conn: Connection,
    id_transaccion: int,
    bloquear: bool = False,
) -> Fila | None:
    origen = (
        """
        FROM Transacciones.Transaccion t WITH (UPDLOCK, HOLDLOCK)
        JOIN Cuentas.Cuenta c ON c.IdCuenta = t.IdCuenta
        WHERE t.IdTransaccion = :id
        """
        if bloquear
        else """
        FROM Transacciones.Transaccion t
        JOIN Cuentas.Cuenta c ON c.IdCuenta = t.IdCuenta
        WHERE t.IdTransaccion = :id
        """
    )

    consulta = "SELECT" + _COLUMNAS + origen

    fila = (
        conn.execute(
            text(consulta),
            {"id": id_transaccion},
        )
        .mappings()
        .first()
    )

    return dict(fila) if fila is not None else None


# --- CAJ-09/11 y TRX-03: escritura -----------------------------


def buscar_por_registro_unico(
    conn: Connection,
    registro_unico: str,
) -> Fila | None:
    """Busca una transacción previa y bloquea el registro."""

    fila = (
        conn.execute(
            text(
                """
                SELECT
                    t.IdTransaccion,
                    t.NumeroComprobante,
                    t.TipoTransaccion,
                    t.Estado,
                    t.CodigoRespuesta,
                    t.Monto,
                    t.IdCuenta,
                    t.IdJornadaCaja,
                    t.CreadoPor,
                    t.FechaHoraSistema,
                    t.NumeroAutorizacion
                FROM Transacciones.Transaccion AS t
                    WITH (UPDLOCK, HOLDLOCK)
                WHERE t.RegistroUnico = :registro_unico
                """
            ),
            {"registro_unico": registro_unico},
        )
        .mappings()
        .first()
    )

    return dict(fila) if fila is not None else None


def obtener_cuenta(
    conn: Connection,
    id_cuenta: int,
) -> Fila | None:
    """Obtiene y bloquea la cuenta durante la operación."""

    fila = (
        conn.execute(
            text(
                """
                SELECT
                    IdCuenta,
                    IdAgencia,
                    Saldo,
                    SaldoRetenido,
                    Estado
                FROM Cuentas.Cuenta WITH (UPDLOCK, HOLDLOCK)
                WHERE IdCuenta = :id
                """
            ),
            {"id": id_cuenta},
        )
        .mappings()
        .first()
    )

    return dict(fila) if fila is not None else None


def saldo_disponible(
    conn: Connection,
    id_cuenta: int,
) -> Any:
    """Calcula el saldo disponible de la cuenta."""

    return conn.execute(
        text(
            """
            SELECT Saldo - SaldoRetenido
            FROM Cuentas.Cuenta
            WHERE IdCuenta = :id
            """
        ),
        {"id": id_cuenta},
    ).scalar_one()


def autorizar_operacion(
    conn: Connection,
    id_cuenta: int,
    id_canal: int,
    tipo: str,
    monto: Any,
) -> Fila:
    """Ejecuta Transacciones.usp_AutorizarOperacion."""

    return ejecutar_con_salidas(
        conn,
        """
        SET NOCOUNT ON;

        DECLARE
            @CodigoRespuesta char(2),
            @Mensaje nvarchar(400),
            @Comision decimal(18, 2),
            @Ahora datetime2 = GETDATE();

        EXEC Transacciones.usp_AutorizarOperacion
            @IdCuenta = ?,
            @IdCanal = ?,
            @TipoTransaccion = ?,
            @Monto = ?,
            @FechaHora = @Ahora,
            @CodigoRespuesta = @CodigoRespuesta OUTPUT,
            @Mensaje = @Mensaje OUTPUT,
            @Comision = @Comision OUTPUT;

        SELECT
            @CodigoRespuesta AS CodigoRespuesta,
            @Mensaje AS Mensaje,
            @Comision AS Comision;
        """,
        (id_cuenta, id_canal, tipo, monto),
    )


def insertar_transaccion(
    conn: Connection,
    datos: dict[str, Any],
) -> int:
    """Inserta una transacción y devuelve su identificador."""

    fila = conn.execute(
        text(
            """
            SET NOCOUNT ON;

            DECLARE @ids TABLE (Id bigint);
            DECLARE @Ahora datetime2 = GETDATE();

            INSERT INTO Transacciones.Transaccion (
                NumeroComprobante,
                Secuencial,
                RegistroUnico,
                NumeroAutorizacion,
                MTI,
                CodigoProcesamiento,
                STAN,
                RRN,
                TipoOperacion,
                TipoTransaccion,
                IdCuenta,
                IdCuentaDestino,
                IdCanal,
                IdAgencia,
                IdJornadaCaja,
                IdTransaccionRelacionada,
                Monto,
                CodigoPaisOrigen,
                FechaHoraSistema,
                FechaRegistro,
                CodigoRespuesta,
                DireccionIP,
                Estado,
                CreadoPor,
                IdFechaContable,
                FechaSistema,
                HoraSistema,
                FechaDispositivo,
                HoraDispositivo
            )
            OUTPUT INSERTED.IdTransaccion INTO @ids
            VALUES (
                :numero_comprobante,
                :secuencial,
                :registro_unico,
                :numero_autorizacion,
                :mti,
                :codigo_procesamiento,
                :stan,
                :rrn,
                :tipo_operacion,
                :tipo_transaccion,
                :id_cuenta,
                :id_cuenta_destino,
                :id_canal,
                :id_agencia,
                :id_jornada,
                :id_relacionada,
                :monto,
                :codigo_pais,
                @Ahora,
                @Ahora,
                :codigo_respuesta,
                :ip,
                :estado,
                :creado_por,
                :id_fecha_contable,
                CAST(@Ahora AS date),
                CAST(@Ahora AS time),
                CAST(@Ahora AS date),
                CAST(@Ahora AS time)
            );

            SELECT Id FROM @ids;
            """
        ),
        datos,
    ).first()

    if fila is None:
        raise RuntimeError("La BD no devolvió el id de la transacción")

    return int(fila[0])


def aplicar_movimiento_cuenta(
    conn: Connection,
    id_transaccion: int,
    id_cuenta: int,
    tipo: str,
    rol: str | None,
    monto: Any,
    id_fecha_contable: int,
) -> int:
    """Aplica el movimiento de crédito o débito a la cuenta."""

    salida = ejecutar_con_salidas(
        conn,
        """
        SET NOCOUNT ON;

        DECLARE @IdMovimiento bigint;

        EXEC Cuentas.usp_AplicarMovimientoCuenta
            @IdTransaccion = ?,
            @IdCuenta = ?,
            @TipoMovimiento = ?,
            @RolCuenta = ?,
            @Monto = ?,
            @IdFechaContable = ?,
            @IdMovimiento = @IdMovimiento OUTPUT;

        SELECT @IdMovimiento AS IdMovimiento;
        """,
        (
            id_transaccion,
            id_cuenta,
            tipo,
            rol,
            monto,
            id_fecha_contable,
        ),
    )

    return int(salida["IdMovimiento"])


def id_tipo_movimiento_caja(
    conn: Connection,
    codigo: str,
) -> int | None:
    """Obtiene el identificador del tipo de movimiento de caja."""

    valor = conn.execute(
        text(
            """
            SELECT IdTipoMovimientoCaja
            FROM Caja.TipoMovimientoCaja
            WHERE Codigo = :codigo
            """
        ),
        {"codigo": codigo},
    ).scalar()

    return int(valor) if valor is not None else None


def insertar_movimiento_caja(
    conn: Connection,
    id_transaccion: int,
    id_jornada: int,
    id_agencia: str,
    id_tipo: int,
    monto: Any,
    observacion: str | None,
    id_asiento: int | None,
    id_fecha_contable: int,
) -> None:
    """Registra el movimiento físico de caja."""

    conn.execute(
        text(
            """
            INSERT INTO Caja.MovimientosCaja (
                IdTransaccion,
                IdJornadaCaja,
                IdAgencia,
                IdTipoMovimiento,
                Monto,
                FechaHora,
                Observacion,
                IdAsientoContable,
                IdFechaContable
            )
            VALUES (
                :id_transaccion,
                :id_jornada,
                :id_agencia,
                :id_tipo,
                :monto,
                GETDATE(),
                :observacion,
                :id_asiento,
                :id_fecha_contable
            )
            """
        ),
        {
            "id_transaccion": id_transaccion,
            "id_jornada": id_jornada,
            "id_agencia": id_agencia,
            "id_tipo": id_tipo,
            "monto": monto,
            "observacion": observacion,
            "id_asiento": id_asiento,
            "id_fecha_contable": id_fecha_contable,
        },
    )


def comision_de(
    conn: Connection,
    id_transaccion: int,
) -> Any:
    """Obtiene la comisión total de una transacción."""

    return conn.execute(
        text(
            """
            SELECT COALESCE(SUM(MontoAplicado), 0)
            FROM Transacciones.TransaccionComision
            WHERE IdTransaccion = :id
            """
        ),
        {"id": id_transaccion},
    ).scalar_one()


# --- TRX-03: reverso de transacciones ----------


def existe_reverso(conn: Connection, id_transaccion: int) -> bool:
    valor = conn.execute(
        text(
            """
            SELECT TOP (1) 1
            FROM Transacciones.Transaccion WITH (UPDLOCK, HOLDLOCK)
            WHERE IdTransaccionRelacionada = :id
              AND TipoOperacion = 'Reverso'
            """
        ),
        {"id": id_transaccion},
    ).scalar()

    return valor is not None


def movimientos_de_transaccion(
    conn: Connection,
    id_transaccion: int,
) -> list[Fila]:
    filas = conn.execute(
        text(
            """
            SELECT
                IdMovimiento,
                IdCuenta,
                TipoMovimiento,
                RolCuenta,
                Monto
            FROM Cuentas.MovimientoTransaccion
            WHERE IdTransaccion = :id
            ORDER BY IdMovimiento
            """
        ),
        {"id": id_transaccion},
    ).mappings()

    return [dict(fila) for fila in filas]


def movimiento_caja_de_transaccion(
    conn: Connection,
    id_transaccion: int,
) -> Fila | None:
    fila = (
        conn.execute(
            text(
                """
                SELECT TOP (1)
                    mc.IdJornadaCaja,
                    mc.IdAgencia,
                    mc.Monto,
                    tm.Codigo,
                    tm.Naturaleza
                FROM Caja.MovimientosCaja AS mc
                JOIN Caja.TipoMovimientoCaja AS tm
                    ON tm.IdTipoMovimientoCaja = mc.IdTipoMovimiento
                WHERE mc.IdTransaccion = :id
                """
            ),
            {"id": id_transaccion},
        )
        .mappings()
        .first()
    )

    return dict(fila) if fila is not None else None


def marcar_reversada(
    conn: Connection,
    id_transaccion: int,
) -> bool:
    resultado = conn.execute(
        text(
            """
            UPDATE Transacciones.Transaccion
            SET Estado = 'Reversada'
            WHERE IdTransaccion = :id
              AND Estado = 'Completada'
              AND TipoOperacion = 'Normal'
            """
        ),
        {"id": id_transaccion},
    )

    return resultado.rowcount == 1

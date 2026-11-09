"""SQL parametrizado ATM-02. Una única transacción del llamador; sin movimientos."""

from typing import Any

from sqlalchemy import Connection, text


def bloquear_contexto(conn: Connection, id_atm: int, id_tarjeta: int) -> None:
    """Mantener estable el terminal y la vinculación mientras se registra la consulta."""
    conn.execute(
        text("""
        SELECT IdATM FROM ATM.ATM WITH (UPDLOCK, HOLDLOCK) WHERE IdATM = :id
    """),
        {"id": id_atm},
    ).scalar_one_or_none()
    conn.execute(
        text("""
        SELECT IdTarjeta FROM Tarjeta.Tarjeta WITH (UPDLOCK, HOLDLOCK)
        WHERE IdTarjeta = :id
    """),
        {"id": id_tarjeta},
    ).scalar_one_or_none()


def buscar_registro(conn: Connection, registro: str) -> dict[str, Any] | None:
    fila = (
        conn.execute(
            text("""
        SELECT IdTransaccion, NumeroComprobante, TipoTransaccion, TipoOperacion,
               IdCuenta, IdTarjeta, IdATM, IdCanal, MTI, Monto, CodigoProcesamiento,
               CodigoRespuesta, Estado, FechaHoraSistema, STAN, RRN, Secuencial
        FROM Transacciones.Transaccion WITH (UPDLOCK, HOLDLOCK)
        WHERE RegistroUnico = :registro
    """),
            {"registro": registro},
        )
        .mappings()
        .one_or_none()
    )
    return dict(fila) if fila is not None else None


def leer_cuenta(conn: Connection, id_cuenta: int) -> dict[str, Any] | None:
    fila = (
        conn.execute(
            text("""
        SELECT c.IdCuenta, c.IdAgencia, c.Estado, c.Saldo, c.SaldoRetenido,
               p.TipoCuenta,
               CONVERT(datetime2, SYSDATETIMEOFFSET() AT TIME ZONE
                   'SA Pacific Standard Time') AS Ahora
        FROM Cuentas.Cuenta c WITH (UPDLOCK, HOLDLOCK)
        JOIN ProductosFinancieros.Producto p ON p.IdProducto = c.IdProducto
        WHERE c.IdCuenta = :id
    """),
            {"id": id_cuenta},
        )
        .mappings()
        .one_or_none()
    )
    return dict(fila) if fila is not None else None


def fecha_contable(conn: Connection, ahora) -> int | None:
    return conn.execute(
        text("SELECT Contabilidad.fn_IdFechaContable(:ahora)"), {"ahora": ahora}
    ).scalar_one_or_none()


def insertar_consulta(conn: Connection, datos: dict[str, Any]) -> int:
    # OUTPUT INTO es compatible con una tabla que tenga triggers habilitados.
    # Campos no proporcionados conservan sus defaults/NULL del esquema existente.
    return int(
        conn.execute(
            text("""
        SET NOCOUNT ON;
        DECLARE @ids TABLE (Id bigint);
        INSERT INTO Transacciones.Transaccion (
            NumeroComprobante, Secuencial, RegistroUnico, MTI,
            CodigoProcesamiento, STAN, RRN, TipoOperacion, TipoTransaccion,
            IdCuenta, IdTarjeta, IdATM, IdCanal, IdAgencia, Monto,
            FechaHoraSistema, FechaRegistro, CodigoRespuesta, Estado,
            CreadoPor, IdFechaContable, FechaSistema, HoraSistema,
            FechaDispositivo, HoraDispositivo, DireccionIP
        ) OUTPUT INSERTED.IdTransaccion INTO @ids VALUES (
            :comprobante, :secuencial, :registro, '0200', :procesamiento,
            :stan, :rrn, 'Normal', 'Consulta', :cuenta, :tarjeta, :atm,
            :canal, :agencia, 0, :ahora, :ahora, :respuesta, :estado,
            :usuario, :fecha_contable, CAST(:ahora AS date), CAST(:ahora AS time),
            CAST(:ahora AS date), CAST(:ahora AS time), :ip
        );
        SELECT Id FROM @ids;
    """),
            datos,
        ).scalar_one()
    )

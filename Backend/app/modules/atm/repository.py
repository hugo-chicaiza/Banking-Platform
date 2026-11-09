from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, text

from app.core.database.procedimientos import ejecutar_con_salidas


def sesion_atm_revocada(conn: Connection, jti: str) -> bool:
    """Leer siempre del primario, sin caché ni lecturas sucias."""
    return (
        conn.execute(
            text("SELECT 1 FROM Seguridad.SesionesATMRevocadas WHERE Jti = :jti"),
            {"jti": jti},
        ).scalar_one_or_none()
        is not None
    )


def revocar_sesion_atm(conn: Connection, jti: str, expiracion: datetime) -> None:
    """Transacción del llamador: serializa inserciones del mismo Jti mediante PK.

    HOLDLOCK protege también el rango cuando todavía no existe la fila. Nunca
    actualizar la fecha de una revocación existente ni extender su expiración.
    """
    existe = conn.execute(
        text("""
            SELECT 1 FROM Seguridad.SesionesATMRevocadas WITH (UPDLOCK, HOLDLOCK)
            WHERE Jti = :jti
        """),
        {"jti": jti},
    ).scalar_one_or_none()
    if existe is None:
        conn.execute(
            text("""
                INSERT INTO Seguridad.SesionesATMRevocadas (Jti, FechaExpiracion)
                VALUES (:jti, :expiracion)
            """),
            {"jti": jti, "expiracion": expiracion.astimezone(UTC).replace(tzinfo=None)},
        )


def obtener_atm(
    conn: Connection,
    codigo_atm: str,
) -> dict[str, Any] | None:
    """Obtiene un terminal ATM junto con la configuración de su canal."""

    sql = text("""
        SELECT
            a.IdATM AS id_atm,
            a.CodigoATM AS codigo_atm,
            a.TipoTerminal AS tipo_terminal,
            a.Estado AS estado_atm,
            c.IdCanal AS id_canal,
            c.CodigoCanal AS codigo_canal,
            c.Estado AS estado_canal,
            c.RequiereTarjeta AS requiere_tarjeta,
            c.RequierePin AS requiere_pin,
            c.RequiereTerminal AS requiere_terminal
        FROM ATM.ATM AS a
        INNER JOIN Canal.Canal AS c
            ON a.IdCanal = c.IdCanal
        WHERE a.CodigoATM = :codigo_atm
    """)

    fila = (
        conn.execute(
            sql,
            {"codigo_atm": codigo_atm},
        )
        .mappings()
        .first()
    )

    return dict(fila) if fila is not None else None


def obtener_tarjeta(
    conn: Connection,
    id_tarjeta: int,
) -> dict[str, Any] | None:
    """Obtiene los datos necesarios para validar una tarjeta."""

    sql = text("""
        SELECT
            t.IdTarjeta AS id_tarjeta,
            t.IdCliente AS id_cliente,
            t.IdCuenta AS id_cuenta,
            t.NombresTitular AS nombres_titular,
            t.ApellidosTitular AS apellidos_titular,
            t.PinAsignado AS pin_asignado,
            t.TipoTarjeta AS tipo_tarjeta,
            t.FechaEmision AS fecha_emision,
            t.FechaExpiracion AS fecha_expiracion,
            t.Estado AS estado_tarjeta,
            t.HashNumeroTarjeta AS hash_numero_tarjeta
        FROM Tarjeta.Tarjeta AS t
        WHERE t.IdTarjeta = :id_tarjeta
    """)

    fila = (
        conn.execute(
            sql,
            {"id_tarjeta": id_tarjeta},
        )
        .mappings()
        .first()
    )

    return dict(fila) if fila is not None else None


def obtener_cuentas_autorizadas(
    conn: Connection, id_tarjeta: int
) -> list[dict[str, Any]]:
    """Solo la cuenta activa vinculada a la tarjeta, incluidas las extensiones."""
    filas = conn.execute(
        text(
            """
            SELECT c.IdCuenta AS id_cuenta, c.NumeroCuenta AS numero_cuenta,
                   p.TipoCuenta AS tipo_cuenta
            FROM Tarjeta.Tarjeta AS t
            INNER JOIN Cuentas.Cuenta AS c ON c.IdCuenta = t.IdCuenta
            INNER JOIN ProductosFinancieros.Producto AS p ON p.IdProducto = c.IdProducto
            WHERE t.IdTarjeta = :id_tarjeta AND t.Estado = 'Activa'
              AND c.Estado = 'Activa' AND p.TipoCuenta IN ('Ahorro', 'Corriente')
            """
        ),
        {"id_tarjeta": id_tarjeta},
    ).mappings()
    return [dict(fila) for fila in filas]


def obtener_estado_pin(
    conn: Connection,
    id_tarjeta: int,
) -> dict[str, Any] | None:
    """Consulta el estado del PIN, los intentos fallidos y el Offset."""

    sql = text("""
        SELECT
            ID_Tarjeta AS id_tarjeta,
            TienePINAsignado AS tiene_pin_asignado,
            IntentosFallidos AS intentos_fallidos,
            Estado AS estado_pin,
            FechaBloqueo AS fecha_bloqueo,
            PINOffset AS pin_offset,
            ReferenciaClavePVK AS referencia_clave_pvk,
            RequiereCambio AS requiere_cambio
        FROM Tarjetas.TarjetaPIN
        WHERE ID_Tarjeta = :id_tarjeta
    """)

    fila = (
        conn.execute(
            sql,
            {"id_tarjeta": id_tarjeta},
        )
        .mappings()
        .first()
    )

    return dict(fila) if fila is not None else None


def bloquear_tarjeta_por_pin(
    conn: Connection,
    id_tarjeta: int,
    id_canal: int,
    usuario: int,
    ip: str | None,
) -> None:
    """Bloqueo idempotente y TarjetaHis en la transacción del llamador; canal ATM."""
    estado = conn.execute(
        text(
            "SELECT Estado FROM Tarjeta.Tarjeta WITH (UPDLOCK, ROWLOCK) WHERE IdTarjeta = :id"
        ),
        {"id": id_tarjeta},
    ).scalar_one_or_none()
    if estado != "Activa":
        # No sobrescribir cancelaciones/vencimientos ni duplicar historial.
        return
    conn.execute(
        text(
            "UPDATE Tarjeta.Tarjeta SET Estado = 'Bloqueada' WHERE IdTarjeta = :id AND Estado = 'Activa'"
        ),
        {"id": id_tarjeta},
    )
    conn.execute(
        text("""
            INSERT INTO Tarjeta.TarjetaHis (
                IdTarjeta, TipoEvento, EstadoAnterior, EstadoActual, Descripcion,
                IdCanal, RealizadoPor, DireccionIP
            ) VALUES (
                :id, 'Bloqueo', 'Activa', 'Bloqueada',
                'Bloqueo por intentos de PIN en ATM', :canal, :usuario, :ip
            )
        """),
        {"id": id_tarjeta, "canal": id_canal, "usuario": usuario, "ip": ip},
    )


def activar_tarjeta_credito(
    conn: Connection,
    id_tarjeta: int,
    id_canal: int,
    usuario: int,
    ip: str | None,
) -> None:
    """A-05: Generada → Activa al cumplir el plazo, con TarjetaHis, en la transacción
    del llamador. Idempotente: si otra petición ya la activó, no hace nada.
    """
    # Consumir todos los resultados evita depender de los contadores intermedios
    # del driver cuando NOCOUNT está desactivado.
    ejecutar_con_salidas(
        conn,
        """
            DECLARE @id int = ?, @canal int = ?, @usuario int = ?;
            DECLARE @ip varchar(45) = ?;
            DECLARE @activadas TABLE (IdTarjeta int);

            UPDATE Tarjeta.Tarjeta SET Estado = 'Activa'
            OUTPUT INSERTED.IdTarjeta INTO @activadas
            WHERE IdTarjeta = @id AND Estado = 'Generada' AND TipoTarjeta = 'Credito';

            INSERT INTO Tarjeta.TarjetaHis (
                IdTarjeta, TipoEvento, EstadoAnterior, EstadoActual, Descripcion,
                IdCanal, RealizadoPor, DireccionIP
            ) SELECT
                IdTarjeta, 'Activacion', 'Generada', 'Activa',
                'Activación automática: 3 días laborables desde la emisión',
                @canal, @usuario, @ip
            FROM @activadas;

            SELECT COUNT(*) AS Activadas FROM @activadas;
        """,
        (id_tarjeta, id_canal, usuario, ip),
    )


def guardar_resultado_pin(
    conn: Connection,
    id_tarjeta: int,
    pin_correcto: bool,
) -> dict[str, Any] | None:

    if pin_correcto:
        sql = text("""
            UPDATE Tarjetas.TarjetaPIN
            SET IntentosFallidos = 0
            OUTPUT
                INSERTED.IntentosFallidos AS intentos_fallidos,
                INSERTED.Estado AS estado_pin
            WHERE ID_Tarjeta = :id_tarjeta
              AND Estado = 'Activo'
              AND TienePINAsignado = 1
              AND IntentosFallidos < 3
        """)
    else:
        sql = text("""
            UPDATE Tarjetas.TarjetaPIN
            SET
                IntentosFallidos = IntentosFallidos + 1,
                Estado = CASE
                    WHEN IntentosFallidos + 1 >= 3
                        THEN 'Bloqueado'
                    ELSE Estado
                END,
                FechaBloqueo = CASE
                    WHEN IntentosFallidos + 1 >= 3
                        THEN SYSUTCDATETIME()
                    ELSE FechaBloqueo
                END
            OUTPUT
                INSERTED.IntentosFallidos AS intentos_fallidos,
                INSERTED.Estado AS estado_pin
            WHERE ID_Tarjeta = :id_tarjeta
              AND Estado = 'Activo'
              AND TienePINAsignado = 1
              AND IntentosFallidos < 3
        """)

    fila = (
        conn.execute(
            sql,
            {"id_tarjeta": id_tarjeta},
        )
        .mappings()
        .first()
    )

    return dict(fila) if fila is not None else None


def obtener_pin_para_verificacion(
    conn: Connection,
    id_tarjeta: int,
) -> dict[str, Any] | None:
    """Bloquea la fila del PIN durante la verificación."""

    sql = text("""
        SELECT
            ID_Tarjeta AS id_tarjeta,
            TienePINAsignado AS tiene_pin_asignado,
            IntentosFallidos AS intentos_fallidos,
            Estado AS estado_pin,
            PINOffset AS pin_offset,
            ReferenciaClavePVK AS referencia_clave_pvk,
            FechaAsignacion AS fecha_asignacion,
            RequiereCambio AS requiere_cambio
        FROM Tarjetas.TarjetaPIN WITH (UPDLOCK, ROWLOCK)
        WHERE ID_Tarjeta = :id_tarjeta
    """)

    fila = (
        conn.execute(
            sql,
            {"id_tarjeta": id_tarjeta},
        )
        .mappings()
        .first()
    )

    return dict(fila) if fila is not None else None


def obtener_asignacion_pin_actual(
    conn: Connection, id_tarjeta: int
) -> dict[str, Any] | None:
    """Solo estado de autorización; no recuperar material criptográfico."""
    fila = (
        conn.execute(
            text("""
            SELECT FechaAsignacion AS fecha_asignacion,
                   TienePINAsignado AS tiene_pin_asignado,
                   Estado AS estado_pin, IntentosFallidos AS intentos_fallidos,
                   RequiereCambio AS requiere_cambio
            FROM Tarjetas.TarjetaPIN WHERE ID_Tarjeta = :id_tarjeta
        """),
            {"id_tarjeta": id_tarjeta},
        )
        .mappings()
        .one_or_none()
    )
    return dict(fila) if fila is not None else None

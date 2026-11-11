"""Persistencia de ATM-06. Todas las transacciones pertenecen al coordinador."""

from typing import Any

from sqlalchemy import Connection, text

from app.core.database.procedimientos import ejecutar_con_salidas


def _lote(conn: Connection, sql: str, datos: dict[str, Any]) -> None:
    """Consumir TODOS los resultados ODBC, incluidos errores diferidos."""
    compilado = text(sql + "\nSELECT 1 AS Confirmado;").compile(dialect=conn.dialect)
    ejecutar_con_salidas(
        conn, str(compilado), tuple(datos[k] for k in (compilado.positiontup or ()))
    )


def bloquear_tarjeta(conn: Connection, tarjeta: int) -> None:
    conn.execute(
        text(
            "SELECT IdTarjeta FROM Tarjeta.Tarjeta WITH (UPDLOCK, HOLDLOCK) WHERE IdTarjeta=:id"
        ),
        {"id": tarjeta},
    ).all()


def leer_operacion(conn: Connection, operacion: str) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text(
                "SELECT * FROM Tarjetas.CambioPINATMOperacion WITH (UPDLOCK, HOLDLOCK) WHERE IdOperacion=:id"
            ),
            {"id": operacion},
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def identificar_operacion(conn: Connection, operacion: str) -> int | None:
    # Lectura de enrutamiento: despues se relee todo bajo los bloqueos comunes.
    return conn.execute(
        text(
            "SELECT ID_Tarjeta FROM Tarjetas.CambioPINATMOperacion WHERE IdOperacion=:id"
        ),
        {"id": operacion},
    ).scalar_one_or_none()


def hay_pendiente(conn: Connection, tarjeta: int) -> bool:
    return (
        conn.execute(
            text(
                "SELECT 1 FROM Tarjetas.CambioPINATMOperacion WITH (UPDLOCK, HOLDLOCK) WHERE ID_Tarjeta=:id AND FechaFinalizacionUTC IS NULL"
            ),
            {"id": tarjeta},
        ).scalar_one_or_none()
        is not None
    )


def dentro_ventana(conn: Connection, operacion: str, max_edad: int) -> bool:
    """Consultar tras bloquear PIN y operacion; reloj autoritativo SQL UTC."""
    return (
        conn.scalar(
            text("""
        SELECT 1 FROM Tarjetas.CambioPINATMOperacion
        WHERE IdOperacion=:id
          AND FechaInicioUTC >= DATEADD(second, -:edad, SYSUTCDATETIME());
    """),
            {"id": operacion, "edad": max_edad},
        )
        is not None
    )


def insertar_operacion(conn: Connection, datos: dict[str, Any]) -> None:
    conn.execute(
        text("""
        INSERT INTO Tarjetas.CambioPINATMOperacion (
            IdOperacion, ID_TarjetaPIN, ID_Tarjeta, IdATM, IdCanal,
            ActorAuditoria, DireccionIP, JtiOrigen, ExpiracionSesionUTC,
            VersionAnterior, VersionNueva, RequiereActivacion, Estado
        ) SELECT :operacion, ID_TarjetaPIN, ID_Tarjeta, :atm, :canal,
            :actor, :ip, :jti, :expiracion, :anterior, FechaAsignacion,
            :activar, 'PIN_CONFIRMADO'
          FROM Tarjetas.TarjetaPIN WHERE ID_Tarjeta=:tarjeta;
    """),
        datos,
    )


def registrar_fecha_cambio(conn: Connection, tarjeta: int) -> None:
    conn.execute(
        text("""
        UPDATE Tarjetas.TarjetaPIN SET FechaUltimoCambio=FechaAsignacion
        WHERE ID_Tarjeta=:id;
    """),
        {"id": tarjeta},
    )


def leer_marcador(conn: Connection, operacion: str) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text(
                "SELECT * FROM Tarjeta.CambioPINATMAplicado WITH (UPDLOCK, HOLDLOCK) WHERE IdOperacion=:id"
            ),
            {"id": operacion},
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def aplicar_cooperativa(conn: Connection, op: dict[str, Any]) -> None:
    # OUTPUT INTO funciona con los triggers existentes y NOCOUNT ON/OFF.
    _lote(
        conn,
        """
        SET NOCOUNT ON;
        DECLARE @cambio TABLE (Id bigint);
        DECLARE @activacion TABLE (Id bigint);
        DECLARE @tarjeta TABLE (Id int);
        IF :activar = 1
        BEGIN
            UPDATE Tarjeta.Tarjeta SET Estado='Activa'
            OUTPUT INSERTED.IdTarjeta INTO @tarjeta
            WHERE IdTarjeta=:tarjeta AND Estado='Generada' AND TipoTarjeta='Debito';
            IF (SELECT COUNT(*) FROM @tarjeta) <> 1 THROW 52146, 'Activacion no confirmada.', 1;
            INSERT INTO Tarjeta.TarjetaHis (
                IdTarjeta, TipoEvento, EstadoAnterior, EstadoActual,
                Descripcion, IdCanal, RealizadoPor, DireccionIP
            ) OUTPUT INSERTED.IdHistorial INTO @activacion
            VALUES (:tarjeta, 'Activacion', 'Generada', 'Activa',
                'Activacion por cambio de PIN en ATM', :canal, :actor, :ip);
        END;
        INSERT INTO Tarjeta.TarjetaHis (
            IdTarjeta, TipoEvento, EstadoAnterior, EstadoActual,
            Descripcion, IdCanal, RealizadoPor, DireccionIP
        ) OUTPUT INSERTED.IdHistorial INTO @cambio
        VALUES (:tarjeta, 'CambioPin', 'Activa', 'Activa',
            'Cambio de PIN en ATM', :canal, :actor, :ip);
        INSERT INTO Tarjeta.CambioPINATMAplicado (
            IdOperacion, IdTarjeta, VersionPIN, IdATM, IdCanal,
            ActorAuditoria, RequiereActivacion,
            IdHistorialCambioPIN, IdHistorialActivacion
        ) SELECT :operacion, :tarjeta, :version, :atm, :canal, :actor,
            :activar, c.Id, a.Id FROM @cambio c LEFT JOIN @activacion a ON 1=1;
    """,
        {
            "operacion": str(op["IdOperacion"]),
            "tarjeta": op["ID_Tarjeta"],
            "version": op["VersionNueva"],
            "atm": op["IdATM"],
            "canal": op["IdCanal"],
            "actor": op["ActorAuditoria"],
            "activar": op["RequiereActivacion"],
            "ip": op["DireccionIP"],
        },
    )


def avanzar(conn: Connection, operacion: str) -> None:
    conn.execute(
        text("""
        UPDATE Tarjetas.CambioPINATMOperacion SET Estado='COOP_CONFIRMADA'
        WHERE IdOperacion=:id AND Estado='PIN_CONFIRMADO';
    """),
        {"id": operacion},
    )


def finalizar(conn: Connection, op: dict[str, Any]) -> None:
    _lote(
        conn,
        """
        SET NOCOUNT ON;
        DECLARE @pin TABLE (Id int);
        DECLARE @fase TABLE (Id uniqueidentifier);
        UPDATE Tarjetas.TarjetaPIN SET RequiereCambio=0
        OUTPUT INSERTED.ID_Tarjeta INTO @pin
        WHERE ID_Tarjeta=:tarjeta AND FechaAsignacion=CONVERT(datetime, :version)
          AND RequiereCambio=1 AND TienePINAsignado=1
          AND Estado='Activo' AND IntentosFallidos BETWEEN 0 AND 2;
        IF (SELECT COUNT(*) FROM @pin) <> 1 THROW 52146, 'Asignacion no disponible.', 1;
        UPDATE Tarjetas.CambioPINATMOperacion
        SET Estado='COMPLETADA', FechaFinalizacionUTC=SYSUTCDATETIME()
        OUTPUT INSERTED.IdOperacion INTO @fase
        WHERE IdOperacion=:id AND Estado='COOP_CONFIRMADA';
        IF (SELECT COUNT(*) FROM @fase) <> 1 THROW 52146, 'Fase no disponible.', 1;
    """,
        {
            "id": str(op["IdOperacion"]),
            "tarjeta": op["ID_Tarjeta"],
            "version": op["VersionNueva"],
        },
    )

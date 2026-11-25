SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57640, 'Falta confirmar la base destino de E6-04.', 1;

BEGIN TRANSACTION;
IF OBJECT_ID('Catalogo.MotivoBloqueoCuenta','U') IS NULL
BEGIN
    CREATE TABLE Catalogo.MotivoBloqueoCuenta (
        Codigo varchar(30) NOT NULL PRIMARY KEY,
        Nombre nvarchar(100) NOT NULL,
        Estado char(1) NOT NULL CHECK (Estado IN ('A','I'))
    );
END;
INSERT Catalogo.MotivoBloqueoCuenta (Codigo, Nombre, Estado)
SELECT v.Codigo,v.Nombre,'A'
FROM (VALUES ('PREVENTIVO', N'Bloqueo preventivo'), ('ORDEN_AUTORIDAD', N'Orden de autoridad')) v(Codigo,Nombre)
WHERE NOT EXISTS (SELECT 1 FROM Catalogo.MotivoBloqueoCuenta WITH (UPDLOCK,HOLDLOCK) WHERE Codigo=v.Codigo);

IF COL_LENGTH('Cuentas.Cuenta','FechaUltimoMovimientoCliente') IS NULL
    ALTER TABLE Cuentas.Cuenta ADD FechaUltimoMovimientoCliente datetime2 NULL;

EXEC sys.sp_executesql N'CREATE OR ALTER VIEW Cuentas.vw_MovimientoIniciadoPorCliente AS
    SELECT m.IdMovimiento, m.IdCuenta, m.FechaHoraSistema
    FROM Cuentas.MovimientoTransaccion m
    JOIN Transacciones.Transaccion t ON t.IdTransaccion=m.IdTransaccion
    WHERE t.TipoOperacion=''Normal'' AND t.Estado IN (''Completada'',''Reversada'')
      AND t.TipoTransaccion IN (''Deposito'',''Retiro'',''Transferencia_Enviada'',''Pago_Credito'',''Pago_Tarjeta'');';

EXEC sys.sp_executesql N'UPDATE c SET FechaUltimoMovimientoCliente=actividad.Ultimo
    FROM Cuentas.Cuenta c
    JOIN (SELECT IdCuenta,MAX(FechaHoraSistema) Ultimo FROM Cuentas.vw_MovimientoIniciadoPorCliente
          GROUP BY IdCuenta) actividad ON actividad.IdCuenta=c.IdCuenta
    WHERE c.FechaUltimoMovimientoCliente IS NULL OR c.FechaUltimoMovimientoCliente < actividad.Ultimo;';

EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER Cuentas.trg_Movimiento_ActividadCliente
    ON Cuentas.MovimientoTransaccion AFTER INSERT AS
    BEGIN
        SET NOCOUNT ON;
        UPDATE c SET FechaUltimoMovimientoCliente=actividad.Ultimo
        FROM Cuentas.Cuenta c
        JOIN (SELECT m.IdCuenta,MAX(m.FechaHoraSistema) Ultimo
              FROM inserted i JOIN Cuentas.vw_MovimientoIniciadoPorCliente m ON m.IdMovimiento=i.IdMovimiento
              GROUP BY m.IdCuenta) actividad ON actividad.IdCuenta=c.IdCuenta
        WHERE c.FechaUltimoMovimientoCliente IS NULL OR c.FechaUltimoMovimientoCliente < actividad.Ultimo;
    END;';

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('Cuentas.Cuenta')
               AND name='IX_Cuenta_ActividadCliente')
    EXEC sys.sp_executesql N'CREATE INDEX IX_Cuenta_ActividadCliente
      ON Cuentas.Cuenta(Estado,FechaUltimoMovimientoCliente) INCLUDE (FechaActivacion,FechaApertura,IdSubProducto);';
COMMIT TRANSACTION;

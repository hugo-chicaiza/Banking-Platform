SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57650, 'Falta confirmar la base destino de E6-05.', 1;
BEGIN TRANSACTION;
IF COL_LENGTH('Cuentas.Retencion','IdSubProductoOrigen') IS NULL
BEGIN
    ALTER TABLE Cuentas.Retencion ADD IdSubProductoOrigen int NULL;
    EXEC(N'UPDATE r SET IdSubProductoOrigen=c.IdSubProducto
          FROM Cuentas.Retencion r JOIN Cuentas.Cuenta c ON c.IdCuenta=r.IdCuenta;
          ALTER TABLE Cuentas.Retencion ALTER COLUMN IdSubProductoOrigen int NOT NULL;
          ALTER TABLE Cuentas.Retencion ADD CONSTRAINT FK_Retencion_SubProductoOrigen
            FOREIGN KEY (IdSubProductoOrigen) REFERENCES ProductosFinancieros.SubProducto(IdSubProducto);');
END;
COMMIT;

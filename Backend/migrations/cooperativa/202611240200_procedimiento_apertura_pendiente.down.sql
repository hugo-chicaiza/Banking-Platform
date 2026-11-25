SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57611, 'Falta confirmar la base destino de E6-01.', 1;
BEGIN TRANSACTION;
IF COL_LENGTH('Cuentas.CuentaAutorizado','RevocadoEn') IS NOT NULL
BEGIN
    EXEC sys.sp_executesql N'IF EXISTS(SELECT 1 FROM Cuentas.CuentaAutorizado WHERE RevocadoEn IS NOT NULL)
        THROW 57611, ''Existen revocaciones de autorizados que deben conservarse.'', 1;';
    ALTER TABLE Cuentas.CuentaAutorizado DROP COLUMN RevocadoEn;
END;
DECLARE @definicion nvarchar(max);
SELECT @definicion=CONVERT(nvarchar(max),value) FROM sys.extended_properties
WHERE major_id=OBJECT_ID('Cuentas.usp_AbrirCuenta') AND minor_id=0 AND name=N'E601_DefinicionAnterior';
IF @definicion IS NULL THROW 57611, 'Falta la definicion original de apertura.', 1;
IF @definicion NOT LIKE N'%CREATE OR ALTER%'
BEGIN
    DECLARE @inicio int=CHARINDEX(N'CREATE',UPPER(@definicion));
    IF @inicio>0 SET @definicion=STUFF(@definicion,@inicio,6,N'ALTER');
END;
EXEC sys.sp_executesql @definicion;
EXEC sys.sp_dropextendedproperty @name=N'E601_DefinicionAnterior',
     @level0type=N'SCHEMA', @level0name=N'Cuentas', @level1type=N'PROCEDURE', @level1name=N'usp_AbrirCuenta';
COMMIT TRANSACTION;

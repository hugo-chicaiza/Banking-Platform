SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57611, 'Falta confirmar la base destino de E6-01.', 1;
BEGIN TRANSACTION;
IF COL_LENGTH('Cuentas.CuentaAutorizado','RevocadoEn') IS NULL
    ALTER TABLE Cuentas.CuentaAutorizado ADD RevocadoEn datetime2 NULL;
IF OBJECT_ID('Cuentas.usp_AbrirCuenta','P') IS NULL
    THROW 57611, 'Falta el procedimiento de apertura original.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.extended_properties WHERE major_id=OBJECT_ID('Cuentas.usp_AbrirCuenta')
               AND minor_id=0 AND name=N'E601_DefinicionAnterior')
BEGIN
    DECLARE @definicion nvarchar(max)=OBJECT_DEFINITION(OBJECT_ID('Cuentas.usp_AbrirCuenta'));
    IF @definicion IS NULL OR DATALENGTH(@definicion)>7500
        THROW 57611, 'No se puede conservar la definicion de apertura original.', 1;
    DECLARE @respaldo nvarchar(3750)=@definicion;
    EXEC sys.sp_addextendedproperty @name=N'E601_DefinicionAnterior', @value=@respaldo,
         @level0type=N'SCHEMA', @level0name=N'Cuentas', @level1type=N'PROCEDURE', @level1name=N'usp_AbrirCuenta';
END;
EXEC sys.sp_executesql N'
ALTER PROCEDURE Cuentas.usp_AbrirCuenta
    @IdCliente int, @IdSubProducto int, @IdAgencia char(3), @NumeroCuenta varchar(20),
    @MontoAperturaAplicado decimal(18,2), @RealizadoPor int, @IdCuenta int OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @@TRANCOUNT=0 OR @MontoAperturaAplicado IS NULL OR @MontoAperturaAplicado<0
        THROW 57611, ''La apertura requiere transaccion y monto minimo valido.'', 1;
    SET @IdCuenta=NULL;
    DECLARE @nueva TABLE (IdCuenta int);
    INSERT Cuentas.Cuenta (NumeroCuenta,IdCliente,IdSubProducto,IdProducto,IdAgencia,Estado,
        Saldo,SaldoRetenido,CreadoPor,MontoAperturaAplicado)
    OUTPUT inserted.IdCuenta INTO @nueva
    SELECT @NumeroCuenta,@IdCliente,s.IdSubProducto,s.IdProducto,@IdAgencia,
           ''PendienteDeposito'',0,0,@RealizadoPor,@MontoAperturaAplicado
    FROM ProductosFinancieros.SubProducto AS s WHERE s.IdSubProducto=@IdSubProducto;
    SELECT @IdCuenta=IdCuenta FROM @nueva;
    IF @IdCuenta IS NULL THROW 57611, ''El subproducto no existe.'', 1;
    INSERT Cuentas.CuentaEvento (IdCuenta,TipoEvento,EstadoActual,Detalle,RealizadoPor,IdAgencia)
    VALUES (@IdCuenta,''Apertura'',''PendienteDeposito'',N''Apertura sin depósito'',@RealizadoPor,@IdAgencia);
END;';
COMMIT TRANSACTION;

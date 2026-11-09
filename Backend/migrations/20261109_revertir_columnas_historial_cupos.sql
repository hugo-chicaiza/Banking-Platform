-- Reversión solicitada de las cuatro columnas agregadas a Canal.CuposModHis.
-- Exige que estén vacías; conserva las demás columnas, filas y triggers.
-- Repetir el script después de la reversión no vuelve a modificar el esquema.
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'Canal.CuposModHis', N'U') IS NULL
        THROW 57002, N'No existe la tabla Canal.CuposModHis.', 1;

    -- SQL literal diferido: permite ejecutar la reversión aunque alguna columna ya no exista.
    IF COL_LENGTH(N'Canal.CuposModHis', N'MaxTransaccionesDiaAnterior') IS NOT NULL
        EXEC(N'IF EXISTS (SELECT 1 FROM Canal.CuposModHis WITH (TABLOCKX,HOLDLOCK)
                         WHERE MaxTransaccionesDiaAnterior IS NOT NULL)
                   THROW 57003, N''La columna MaxTransaccionesDiaAnterior contiene datos.'', 1;
               ALTER TABLE Canal.CuposModHis DROP COLUMN MaxTransaccionesDiaAnterior;');

    IF COL_LENGTH(N'Canal.CuposModHis', N'MaxTransaccionesDiaNuevo') IS NOT NULL
        EXEC(N'IF EXISTS (SELECT 1 FROM Canal.CuposModHis WITH (TABLOCKX,HOLDLOCK)
                         WHERE MaxTransaccionesDiaNuevo IS NOT NULL)
                   THROW 57003, N''La columna MaxTransaccionesDiaNuevo contiene datos.'', 1;
               ALTER TABLE Canal.CuposModHis DROP COLUMN MaxTransaccionesDiaNuevo;');

    IF COL_LENGTH(N'Canal.CuposModHis', N'FechaVigenciaAnterior') IS NOT NULL
        EXEC(N'IF EXISTS (SELECT 1 FROM Canal.CuposModHis WITH (TABLOCKX,HOLDLOCK)
                         WHERE FechaVigenciaAnterior IS NOT NULL)
                   THROW 57003, N''La columna FechaVigenciaAnterior contiene datos.'', 1;
               ALTER TABLE Canal.CuposModHis DROP COLUMN FechaVigenciaAnterior;');

    IF COL_LENGTH(N'Canal.CuposModHis', N'FechaVigenciaNueva') IS NOT NULL
        EXEC(N'IF EXISTS (SELECT 1 FROM Canal.CuposModHis WITH (TABLOCKX,HOLDLOCK)
                         WHERE FechaVigenciaNueva IS NOT NULL)
                   THROW 57003, N''La columna FechaVigenciaNueva contiene datos.'', 1;
               ALTER TABLE Canal.CuposModHis DROP COLUMN FechaVigenciaNueva;');

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

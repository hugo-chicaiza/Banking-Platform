-- E3-03: migracion propuesta; validar primero en laboratorio local propio.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57603,'Falta confirmar la base destino de E3-03.',1;
IF CONVERT(int,SERVERPROPERTY('EngineEdition'))=5 AND ISNULL(CONVERT(int,SESSION_CONTEXT(N'E303_AZURE_APROBADA')),0)<>1
    THROW 57603,'E3-03 requiere autorizacion adicional para Azure.',1;
BEGIN TRY
    BEGIN TRANSACTION;
    IF OBJECT_ID(N'Canal.fn_CupoVigente') IS NULL
       OR OBJECT_ID(N'Canal.trg_CanalCupoClienteCustom_Tope',N'TR') IS NULL
        THROW 57603, 'No se encontraron los consumidores existentes inspeccionados.', 1;

    EXEC sys.sp_executesql N'CREATE OR ALTER FUNCTION Canal.fn_CupoVigenteFecha(@IdCuenta int,@IdCanal int,@Fecha date)
    RETURNS TABLE AS RETURN
    SELECT CASE WHEN cc.IdCanalCupo IS NULL THEN ''SUBPRODUCTO'' ELSE ''CUENTA'' END AS Origen,
      CASE WHEN cc.CupoDiario<p.CupoDiarioMaximo THEN cc.CupoDiario ELSE p.CupoDiarioMaximo END AS CupoDiario,
      CASE WHEN cc.CupoMensual<p.CupoMensualMaximo THEN cc.CupoMensual ELSE p.CupoMensualMaximo END AS CupoMensual,
      CASE WHEN cc.MontoMaxTransaccion<p.MontoMaxTransaccion THEN cc.MontoMaxTransaccion ELSE p.MontoMaxTransaccion END AS MontoMaxTransaccion,
      CASE WHEN cc.MaxTransaccionesDia<p.MaxTransaccionesDia THEN cc.MaxTransaccionesDia ELSE p.MaxTransaccionesDia END AS MaxTransaccionesDia
    FROM Cuentas.Cuenta cuenta
    JOIN Canal.Canal ca ON ca.IdCanal=@IdCanal AND ca.Estado=''A''
    CROSS APPLY(SELECT TOP(1) x.* FROM ProductosFinancieros.ProductoCanalCupo x
      WHERE x.IdSubProducto=cuenta.IdSubProducto AND x.IdCanal=@IdCanal AND x.EstadoCupo=''A''
        AND x.VigenciaDesde<=@Fecha
        AND (x.VigenciaHasta IS NULL OR x.VigenciaHasta>=@Fecha)
      ORDER BY x.VigenciaDesde DESC,x.IdProductoCanalCupo DESC) p
    LEFT JOIN Canal.CanalCupoClienteCustom cc ON cc.IdCuenta=cuenta.IdCuenta AND cc.IdCanal=@IdCanal
      AND cc.Estado=''A'' AND (cc.FechaVigencia IS NULL OR cc.FechaVigencia>=@Fecha)
    WHERE cuenta.IdCuenta=@IdCuenta';

    EXEC sys.sp_executesql N'CREATE OR ALTER FUNCTION Canal.fn_CupoVigente(@IdCuenta int,@IdCanal int)
    RETURNS TABLE AS RETURN
    SELECT Origen,CupoDiario,CupoMensual,MontoMaxTransaccion,MaxTransaccionesDia
    FROM Canal.fn_CupoVigenteFecha(@IdCuenta,@IdCanal,CONVERT(date,SYSDATETIMEOFFSET() AT TIME ZONE ''SA Pacific Standard Time''))';

    EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER Canal.trg_CanalCupoClienteCustom_Tope
    ON Canal.CanalCupoClienteCustom AFTER INSERT,UPDATE AS
    BEGIN
      SET NOCOUNT ON;
      IF EXISTS(SELECT 1 FROM inserted i JOIN Cuentas.Cuenta cuenta ON cuenta.IdCuenta=i.IdCuenta
        OUTER APPLY(SELECT TOP(1) x.* FROM ProductosFinancieros.ProductoCanalCupo x WITH(UPDLOCK,HOLDLOCK)
          JOIN Canal.Canal ca ON ca.IdCanal=x.IdCanal AND ca.Estado=''A''
          WHERE x.IdSubProducto=cuenta.IdSubProducto AND x.IdCanal=i.IdCanal AND x.EstadoCupo=''A''
            AND x.VigenciaDesde<=CONVERT(date,SYSDATETIMEOFFSET() AT TIME ZONE ''SA Pacific Standard Time'')
            AND (x.VigenciaHasta IS NULL OR x.VigenciaHasta>=CONVERT(date,SYSDATETIMEOFFSET() AT TIME ZONE ''SA Pacific Standard Time''))
          ORDER BY x.VigenciaDesde DESC,x.IdProductoCanalCupo DESC) p
        WHERE i.Estado=''A'' AND (p.IdProductoCanalCupo IS NULL
          OR i.CupoDiario>p.CupoDiarioMaximo OR i.CupoMensual>p.CupoMensualMaximo
          OR i.MontoMaxTransaccion>p.MontoMaxTransaccion OR i.MaxTransaccionesDia>p.MaxTransaccionesDia))
        THROW 52003,''El cupo personalizado no puede superar el techo vigente del subproducto.'',1;
    END';
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

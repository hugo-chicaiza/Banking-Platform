SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57650, 'Falta confirmar la base destino de E6-05.', 1;

DECLARE @definicion nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(N'Contabilidad.usp_ValidarCierreDiario', 'P'));
IF @definicion LIKE N'%E605_CONTROL_RETENIDO%'
BEGIN
    DECLARE @bloque nvarchar(max) = N'
        /* E605_CONTROL_RETENIDO */
        IF @Bloquear = 1 AND EXISTS (SELECT 1 FROM Cuentas.vw_RetenidoDescuadrado)
            THROW 57651, N''Cierre bloqueado: el saldo retenido difiere de la suma de retenciones activas.'', 1;
';
    DECLARE @inicio int = CHARINDEX(N'PROCEDURE', UPPER(@definicion)),
            @posicion int = CHARINDEX(@bloque, @definicion);
    IF @inicio = 0 OR @posicion <= @inicio
        THROW 57650, 'El control de retenidos cambió; revise la reversión antes de continuar.', 1;

    SET @definicion = STUFF(@definicion, @posicion, LEN(@bloque), N'');
    SET @definicion = N'ALTER ' + SUBSTRING(@definicion, @inicio, LEN(@definicion));
    EXEC sys.sp_executesql @definicion;
END;

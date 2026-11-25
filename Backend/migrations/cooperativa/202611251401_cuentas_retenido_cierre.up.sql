SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57650, 'Falta confirmar la base destino de E6-05.', 1;

DECLARE @definicion nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(N'Contabilidad.usp_ValidarCierreDiario', 'P'));
IF @definicion IS NOT NULL AND @definicion NOT LIKE N'%E605_CONTROL_RETENIDO%'
BEGIN
    -- El procedimiento existente conserva permisos, firma y conjuntos de resultados.
    DECLARE @inicio int = CHARINDEX(N'PROCEDURE', UPPER(@definicion)),
            @despues int = CHARINDEX(N'SET NOCOUNT ON;', UPPER(@definicion));
    IF @inicio = 0 OR @despues <= @inicio
        THROW 57650, 'No se reconoce el punto de extensión del validador de cierre.', 1;

    DECLARE @bloque nvarchar(max) = N'
        /* E605_CONTROL_RETENIDO */
        IF @Bloquear = 1 AND EXISTS (SELECT 1 FROM Cuentas.vw_RetenidoDescuadrado)
            THROW 57651, N''Cierre bloqueado: el saldo retenido difiere de la suma de retenciones activas.'', 1;
';
    SET @definicion = STUFF(@definicion, @despues + LEN(N'SET NOCOUNT ON;'), 0, @bloque);
    SET @definicion = N'ALTER ' + SUBSTRING(@definicion, @inicio, LEN(@definicion));
    EXEC sys.sp_executesql @definicion;
END;

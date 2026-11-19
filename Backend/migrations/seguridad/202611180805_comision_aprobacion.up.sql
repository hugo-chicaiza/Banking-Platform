-- Catálogo E0-08 para el cambio sensible de una tarifa E1-12.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57285, N'Confirme la base de seguridad en migration_database.', 1;
BEGIN TRY
    BEGIN TRANSACTION;
    IF NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
                   WHERE CodigoTransaccion = 'PAR-COMISION')
        INSERT Seguridad.TransaccionesInterfaz
            (CodigoTransaccion, NombreTransaccion, Modulo, BaseObjetivo, RolesEjecucion, PermisoAprobacion)
        VALUES ('PAR-COMISION', N'Programar tarifa de comisión', 'Parametros',
                'cooperativa', N'["ADMIN"]', 'parametros:aprobar');
    IF NOT EXISTS (
        SELECT 1 FROM Seguridad.TransaccionesInterfaz
        WHERE CodigoTransaccion = 'PAR-COMISION' AND BaseObjetivo = 'cooperativa'
          AND RolesEjecucion = N'["ADMIN"]' AND PermisoAprobacion = 'parametros:aprobar'
          AND EsSensible = 1 AND Estado = 'A'
    )
        THROW 57286, N'La operación PAR-COMISION tiene una configuración incompatible.', 1;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

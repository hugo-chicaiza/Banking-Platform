SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57730, 'Confirme la base destino de E6-11.', 1;

UPDATE Sistema.Tarea SET Estado='I' WHERE Codigo IN ('TAR_VENCER','TAR_ANULAR_NO_RETIRADAS');

SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57640, 'Falta confirmar la base destino de E6-04.', 1;

DELETE FROM Sistema.Tarea WHERE Codigo='CTA_INACTIVIDAD'
    AND NOT EXISTS (SELECT 1 FROM Sistema.TareaEjecucion WHERE Codigo='CTA_INACTIVIDAD');

UPDATE Seguridad.TransaccionesInterfaz SET Estado='I' WHERE CodigoTransaccion='CTA-ESTADO';

SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57611, 'Falta confirmar la base destino de E6-01.', 1;
BEGIN TRANSACTION;
IF EXISTS(SELECT 1 FROM Sistema.TareaEjecucion WITH (UPDLOCK,HOLDLOCK) WHERE Codigo='CTA_ANULAR_SIN_DEPOSITO')
    THROW 57611, 'La tarea tiene historial de ejecuciones.', 1;
DELETE FROM Sistema.Tarea WHERE Codigo='CTA_ANULAR_SIN_DEPOSITO';
COMMIT TRANSACTION;

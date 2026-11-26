SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57720, 'Confirme la base destino de aprobaciones de tarjetas.', 1;

BEGIN TRANSACTION;
IF OBJECT_ID(N'Tarjeta.SolicitudAprobacionPendiente', N'U') IS NOT NULL
BEGIN
    IF EXISTS (SELECT 1 FROM Tarjeta.SolicitudAprobacionPendiente WITH (UPDLOCK, HOLDLOCK))
        THROW 57721, 'Existen solicitudes de tarjetas; preserve su seguimiento antes de revertir.', 1;
    DROP TABLE Tarjeta.SolicitudAprobacionPendiente;
END;
COMMIT TRANSACTION;

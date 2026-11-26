SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57720, 'Confirme la base destino de aprobaciones de tarjetas.', 1;

BEGIN TRANSACTION;
IF EXISTS (SELECT 1 FROM Seguridad.SolicitudAprobacion WITH (UPDLOCK, HOLDLOCK)
           WHERE CodigoTransaccion = 'TAR-SOLICITAR')
    THROW 57721, 'Existen solicitudes de TAR-SOLICITAR; preserve su historial antes de revertir.', 1;
DELETE FROM Seguridad.TransaccionesInterfaz WHERE CodigoTransaccion = 'TAR-SOLICITAR';
COMMIT TRANSACTION;

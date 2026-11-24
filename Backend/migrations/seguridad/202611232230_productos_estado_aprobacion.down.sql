/* E3-06 · Retira la configuración siempre que no se haya utilizado. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57606, 'Falta confirmar la base destino de E3-06.', 1;

BEGIN TRANSACTION;
IF EXISTS (
    SELECT 1 FROM Seguridad.SolicitudAprobacion WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoTransaccion = 'PRD-ESTADO'
)
    THROW 57606, 'Existen solicitudes de estado; se conserva su historial.', 1;
DELETE FROM Seguridad.TransaccionesInterfaz WHERE CodigoTransaccion = 'PRD-ESTADO';
DELETE FROM Auditoria.TipoEvento WHERE CodigoEvento = 'PRD_ESTADO_CAMBIADO';
COMMIT TRANSACTION;

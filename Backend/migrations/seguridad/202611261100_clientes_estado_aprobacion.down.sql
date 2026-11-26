/* E5-07 abajo: solo retira lo que no tiene uso registrado. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57507, 'Falta confirmar la base destino de E5-07.', 1;

BEGIN TRANSACTION;
DELETE FROM Auditoria.TipoEvento
WHERE CodigoEvento = 'CLI_ESTADO'
  AND NOT EXISTS (SELECT 1 FROM Auditoria.Auditoria AS a WHERE a.CodigoEvento = 'CLI_ESTADO');
DELETE FROM Seguridad.TransaccionesInterfaz
WHERE CodigoTransaccion = 'CLI-ESTADO'
  AND NOT EXISTS (SELECT 1 FROM Seguridad.SolicitudAprobacion WHERE CodigoTransaccion = 'CLI-ESTADO');
COMMIT TRANSACTION;

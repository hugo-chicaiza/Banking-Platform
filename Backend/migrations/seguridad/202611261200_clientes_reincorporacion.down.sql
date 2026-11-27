/* Reincorporación abajo: solo retira lo que no tiene uso registrado. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de la reincorporación.', 1;

BEGIN TRANSACTION;
DELETE FROM Auditoria.TipoEvento
WHERE CodigoEvento = 'CLI_REINCORPORADO'
  AND NOT EXISTS (SELECT 1 FROM Auditoria.Auditoria AS a WHERE a.CodigoEvento = 'CLI_REINCORPORADO');
DELETE FROM Seguridad.TransaccionesInterfaz
WHERE CodigoTransaccion = 'CLI-REINCORPORAR'
  AND NOT EXISTS (SELECT 1 FROM Seguridad.SolicitudAprobacion WHERE CodigoTransaccion = 'CLI-REINCORPORAR');
COMMIT TRANSACTION;

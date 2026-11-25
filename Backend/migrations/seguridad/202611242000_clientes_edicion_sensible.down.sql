/* E5-04 abajo: solo retira lo que no tiene uso registrado. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57504, 'Falta confirmar la base destino de E5-04.', 1;

BEGIN TRANSACTION;
DELETE FROM Auditoria.TipoEvento
WHERE CodigoEvento IN ('CLI_EDITADO', 'CLI_CAMBIO_SENSIBLE')
  AND NOT EXISTS (SELECT 1 FROM Auditoria.Auditoria AS a WHERE a.CodigoEvento = Auditoria.TipoEvento.CodigoEvento);
DELETE FROM Seguridad.TransaccionesInterfaz
WHERE CodigoTransaccion = 'CLI-EDITAR'
  AND NOT EXISTS (SELECT 1 FROM Seguridad.SolicitudAprobacion WHERE CodigoTransaccion = 'CLI-EDITAR');
COMMIT TRANSACTION;

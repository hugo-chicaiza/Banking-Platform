/* E5-06 abajo: solo retira lo que no tiene uso registrado. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57506, 'Falta confirmar la base destino de E5-06.', 1;

BEGIN TRANSACTION;
DELETE FROM Auditoria.TipoEvento
WHERE CodigoEvento IN ('CLI_RIESGO_EVALUADO', 'CLI_HABILITADO')
  AND NOT EXISTS (SELECT 1 FROM Auditoria.Auditoria AS a WHERE a.CodigoEvento = Auditoria.TipoEvento.CodigoEvento);
DELETE FROM Seguridad.TransaccionesInterfaz
WHERE CodigoTransaccion = 'CLI-RIESGO'
  AND NOT EXISTS (SELECT 1 FROM Seguridad.SolicitudAprobacion WHERE CodigoTransaccion = 'CLI-RIESGO');
COMMIT TRANSACTION;

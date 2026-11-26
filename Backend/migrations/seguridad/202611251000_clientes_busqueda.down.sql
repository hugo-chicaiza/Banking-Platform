/* E5-05 abajo: solo retira eventos sin uso registrado. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57505, 'Falta confirmar la base destino de E5-05.', 1;

BEGIN TRANSACTION;
DELETE FROM Auditoria.TipoEvento
WHERE CodigoEvento IN ('CLI_DATO_REVELADO', 'CLI_EXPORTACION')
  AND NOT EXISTS (SELECT 1 FROM Auditoria.Auditoria AS a WHERE a.CodigoEvento = Auditoria.TipoEvento.CodigoEvento);
COMMIT TRANSACTION;

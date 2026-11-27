/* #387: retira del catálogo únicamente los eventos que no tienen historial. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de auditoría de firmantes.', 1;

BEGIN TRANSACTION;
DELETE FROM Auditoria.TipoEvento
WHERE CodigoEvento IN ('CLI_RELACION_INICIADA', 'CLI_RELACION_TERMINADA')
  AND NOT EXISTS (
    SELECT 1 FROM Auditoria.Auditoria AS a
    WHERE a.CodigoEvento = Auditoria.TipoEvento.CodigoEvento
);
COMMIT TRANSACTION;

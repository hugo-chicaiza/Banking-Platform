/* #387: eventos de alta y finalización de firmantes. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de auditoría de firmantes.', 1;

BEGIN TRANSACTION;
INSERT Auditoria.TipoEvento (CodigoEvento, Modulo, Severidad, EnTransaccion)
SELECT e.CodigoEvento, e.Modulo, e.Severidad, e.EnTransaccion
FROM (VALUES ('CLI_RELACION_INICIADA', 'clientes', 'Sensible', 0),
             ('CLI_RELACION_TERMINADA', 'clientes', 'Sensible', 0))
    AS e(CodigoEvento, Modulo, Severidad, EnTransaccion)
WHERE NOT EXISTS (
    SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoEvento = e.CodigoEvento
);
COMMIT TRANSACTION;

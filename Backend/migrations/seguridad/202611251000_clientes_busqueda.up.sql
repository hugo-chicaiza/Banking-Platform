/* E5-05: revelación auditada de datos del cliente y exportación del listado. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57505, 'Falta confirmar la base destino de E5-05.', 1;

BEGIN TRANSACTION;
INSERT Auditoria.TipoEvento (CodigoEvento, Modulo, Severidad, EnTransaccion)
SELECT e.CodigoEvento, e.Modulo, e.Severidad, e.EnTransaccion
FROM (VALUES ('CLI_DATO_REVELADO', 'clientes', 'Sensible', 0),
             ('CLI_EXPORTACION', 'clientes', 'Sensible', 1))
    AS e(CodigoEvento, Modulo, Severidad, EnTransaccion)
WHERE NOT EXISTS (SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK)
                  WHERE CodigoEvento = e.CodigoEvento);
COMMIT TRANSACTION;

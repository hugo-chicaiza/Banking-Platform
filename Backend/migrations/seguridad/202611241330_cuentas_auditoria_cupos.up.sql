SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57613, 'Falta confirmar la base destino de E6-03.', 1;

INSERT INTO Auditoria.TipoEvento (CodigoEvento, Modulo, Severidad, EnTransaccion)
SELECT evento.CodigoEvento, evento.Modulo, evento.Severidad, evento.EnTransaccion
FROM (VALUES ('CTA_CUPO_CAMBIADO', 'cuentas', 'Sensible', 0))
    AS evento(CodigoEvento, Modulo, Severidad, EnTransaccion)
WHERE NOT EXISTS (
    SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoEvento = evento.CodigoEvento
);

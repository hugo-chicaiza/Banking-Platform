/* Catálogo de eventos de confirmación y resolución de bóveda (SeguridadDB). */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57208, 'Falta confirmar la base destino de la migración.', 1;
IF OBJECT_ID('Auditoria.TipoEvento', 'U') IS NULL
    THROW 57208, 'Falta Auditoria.TipoEvento (202611191000).', 1;

MERGE Auditoria.TipoEvento WITH (HOLDLOCK) AS destino USING (VALUES
    ('DESPACHAR_SOLICITUD_BOVEDA', 'boveda', 'Sensible', 1),
    ('RECIBIR_SOLICITUD_BOVEDA', 'boveda', 'Sensible', 1),
    ('DEVOLVER_REMESA_BOVEDA', 'boveda', 'Sensible', 1),
    ('CERRAR_EXCEDENTE_BOVEDA', 'boveda', 'Sensible', 1),
    ('RESOLVER_NOVEDAD_CAJERO', 'boveda', 'Sensible', 1)
) AS origen(CodigoEvento, Modulo, Severidad, EnTransaccion)
ON destino.CodigoEvento = origen.CodigoEvento
WHEN NOT MATCHED THEN INSERT(CodigoEvento, Modulo, Severidad, EnTransaccion)
    VALUES(origen.CodigoEvento, origen.Modulo, origen.Severidad, origen.EnTransaccion);

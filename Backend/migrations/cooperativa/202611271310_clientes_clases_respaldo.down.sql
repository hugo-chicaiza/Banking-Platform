SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de E5-08.', 1;

DELETE c FROM Catalogo.ClaseDocumentoCliente AS c
WHERE c.Codigo IN ('PASAPORTE_DATOS','RESPALDO_TUTOR')
AND NOT EXISTS (SELECT 1 FROM Clientes.ClienteArchivo a WHERE a.ClaseDocumento=c.Codigo);

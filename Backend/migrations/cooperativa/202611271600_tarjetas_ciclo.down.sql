SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57730, 'Confirme la base destino de E6-11.', 1;

-- La reversión del código y las tareas conserva el catálogo, los parámetros
-- eventualmente modificados y las transiciones referidas por el historial.

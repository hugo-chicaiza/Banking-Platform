-- CooperativaDB. The schema already enforces unique codes and a single matrix.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57351, 'Confirme la base destino de E0-10.', 1;
IF OBJECT_ID(N'Organizacion.Agencia', N'U') IS NULL
    THROW 57351, 'Falta Organizacion.Agencia.', 1;

BEGIN TRANSACTION;
IF OBJECT_ID(N'Organizacion.SeqAgenciaId', N'SO') IS NULL
BEGIN
    DECLARE @inicio int;
    SELECT @inicio = COALESCE(MAX(TRY_CONVERT(int, IdAgencia)), 0) + 1
    FROM Organizacion.Agencia WITH (TABLOCKX, HOLDLOCK)
    WHERE IdAgencia COLLATE Latin1_General_100_BIN2 LIKE '[0-9][0-9][0-9]';
    IF @inicio > 999
        THROW 57351, 'No hay identificadores numericos disponibles.', 1;
    DECLARE @sql nvarchar(300) = N'CREATE SEQUENCE Organizacion.SeqAgenciaId AS int START WITH '
        + CONVERT(nvarchar(3), @inicio) + N' INCREMENT BY 1 MINVALUE 1 MAXVALUE 999 NO CYCLE;';
    EXEC sys.sp_executesql @sql;
    EXEC sys.sp_addextendedproperty @name=N'E010_Propietario', @value=N'351',
        @level0type=N'SCHEMA', @level0name=N'Organizacion',
        @level1type=N'SEQUENCE', @level1name=N'SeqAgenciaId';
END;
COMMIT TRANSACTION;

/* E5-10 / #57. CooperativaDB. No cambia ni elimina direcciones existentes. */
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;
    IF OBJECT_ID('Clientes.Direcciones', 'U') IS NULL
        THROW 51057, 'Falta Clientes.Direcciones; revisar la base destino.', 1;

    IF OBJECT_ID('Catalogo.TipoDireccion', 'U') IS NULL
        CREATE TABLE Catalogo.TipoDireccion (
            Codigo varchar(20) NOT NULL CONSTRAINT PK_TipoDireccion PRIMARY KEY,
            Nombre nvarchar(60) NOT NULL,
            Estado char(1) NOT NULL CONSTRAINT DF_TipoDireccion_Estado DEFAULT ('A'),
            CONSTRAINT CK_TipoDireccion_Estado CHECK (Estado IN ('A', 'I'))
        );

    INSERT INTO Catalogo.TipoDireccion (Codigo, Nombre, Estado)
    SELECT v.Codigo, v.Codigo, 'A'
    FROM (VALUES ('Domicilio'), ('Trabajo'), ('Correspondencia'), ('Otra')) v(Codigo)
    WHERE NOT EXISTS (SELECT 1 FROM Catalogo.TipoDireccion t WHERE t.Codigo=v.Codigo);

    /* Conserva también los tipos presentes en los datos, sin inventar equivalencias. */
    INSERT INTO Catalogo.TipoDireccion (Codigo, Nombre, Estado)
    SELECT DISTINCT d.TipoDireccion, d.TipoDireccion, 'A'
    FROM Clientes.Direcciones d
    WHERE d.TipoDireccion IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM Catalogo.TipoDireccion t WHERE t.Codigo=d.TipoDireccion);

    /* Sustituye únicamente checks de esta columna por el catálogo referenciado.
       Un check combinado requiere revisión manual; no se elimina silenciosamente. */
    DECLARE @tabla int = OBJECT_ID('Clientes.Direcciones');
    DECLARE @columna int = COLUMNPROPERTY(@tabla, 'TipoDireccion', 'ColumnId');
    IF EXISTS (
        SELECT 1 FROM sys.check_constraints c
        JOIN sys.sql_expression_dependencies e ON e.referencing_id=c.object_id
        WHERE c.parent_object_id=@tabla AND e.referenced_id=@tabla
          AND e.referenced_minor_id=@columna
          AND EXISTS (SELECT 1 FROM sys.sql_expression_dependencies otra
                      WHERE otra.referencing_id=c.object_id AND otra.referenced_id=@tabla
                        AND otra.referenced_minor_id NOT IN (0, @columna))
    ) THROW 51057, 'Check combinado de TipoDireccion: revisar antes de migrar.', 1;

    DECLARE @sql nvarchar(max)=N'';
    SELECT @sql=@sql+N'ALTER TABLE Clientes.Direcciones DROP CONSTRAINT '+QUOTENAME(c.name)+N';'
    FROM sys.check_constraints c
    WHERE c.parent_object_id=@tabla
      AND (c.parent_column_id=@columna OR EXISTS (
          SELECT 1 FROM sys.sql_expression_dependencies e
          WHERE e.referencing_id=c.object_id AND e.referenced_id=@tabla
            AND e.referenced_minor_id=@columna));
    IF LEN(@sql)>0 EXEC sys.sp_executesql @sql;

    IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE parent_object_id=@tabla
                   AND name='FK_Direcciones_TipoDireccion')
        ALTER TABLE Clientes.Direcciones WITH CHECK
            ADD CONSTRAINT FK_Direcciones_TipoDireccion FOREIGN KEY (TipoDireccion)
            REFERENCES Catalogo.TipoDireccion (Codigo);
    COMMIT;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK;
    THROW;
END CATCH;

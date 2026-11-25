/* E5-05: agencia de registro (definición de E5-02) y nombre normalizado para buscar. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57505, 'Falta confirmar la base destino de E5-05.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH('Clientes.Cliente', 'IdAgenciaRegistro') IS NULL
    ALTER TABLE Clientes.Cliente ADD IdAgenciaRegistro char(3) NULL
        CONSTRAINT FK_Cliente_AgenciaRegistro REFERENCES Organizacion.Agencia (IdAgencia);

/* Mayúsculas y comparación sin acentos; la búsqueda usa "empieza con" por palabra. */
IF COL_LENGTH('Clientes.Cliente', 'NombreBusqueda') IS NULL
    EXEC sys.sp_executesql N'
        ALTER TABLE Clientes.Cliente ADD NombreBusqueda AS
            (CAST(UPPER(CONCAT(Nombres, '' '', Apellidos, '' '', RazonSocial)) AS varchar(760))
                COLLATE Latin1_General_CI_AI) PERSISTED;';

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Cliente_NombreBusqueda'
               AND object_id = OBJECT_ID(N'Clientes.Cliente'))
    EXEC sys.sp_executesql N'CREATE INDEX IX_Cliente_NombreBusqueda ON Clientes.Cliente (NombreBusqueda);';
COMMIT TRANSACTION;

/* E6-12: PAN cifrado fuera de Pruebas, con versión de clave y sin PAN claro. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57720, 'Confirme la base destino de Tarjetas.TarjetaNumeroCifrado.', 1;

BEGIN TRANSACTION;
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'Tarjetas')
    EXEC(N'CREATE SCHEMA Tarjetas');

IF OBJECT_ID(N'Tarjetas.TarjetaNumeroCifrado', N'U') IS NULL
    CREATE TABLE Tarjetas.TarjetaNumeroCifrado (
        IdTarjeta       int NOT NULL,
        TokenTarjeta    varchar(64) NOT NULL,
        NumeroCifrado   varbinary(256) NOT NULL,
        ReferenciaClave varchar(32) NOT NULL,
        VersionClave    smallint NOT NULL,
        FechaCreacion   datetime2 NOT NULL
            CONSTRAINT DF_TarjetaNumeroCifrado_Fecha DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_TarjetaNumeroCifrado PRIMARY KEY (IdTarjeta),
        CONSTRAINT UQ_TarjetaNumeroCifrado_Token UNIQUE (TokenTarjeta),
        CONSTRAINT CK_TarjetaNumeroCifrado_Version CHECK (VersionClave >= 1)
    );

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id=OBJECT_ID(N'Tarjetas.TarjetaNumeroCifrado', N'U')
      AND name=N'VersionClave'
)
    ALTER TABLE Tarjetas.TarjetaNumeroCifrado ADD VersionClave smallint NULL;

COMMIT TRANSACTION;

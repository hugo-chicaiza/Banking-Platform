/* E6-12: identifica la versión de la clave HMAC usada para el hash de búsqueda. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57720, 'Confirme la base destino de la huella HMAC de tarjetas.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH(N'Tarjeta.Tarjeta', N'VersionClaveHuella') IS NULL
    ALTER TABLE Tarjeta.Tarjeta ADD VersionClaveHuella smallint NULL;
IF COL_LENGTH(N'Tarjeta.Tarjeta', N'ReferenciaClaveHuella') IS NULL
    ALTER TABLE Tarjeta.Tarjeta ADD ReferenciaClaveHuella varchar(32) NULL;

COMMIT TRANSACTION;

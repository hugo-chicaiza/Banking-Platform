SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57615, 'Confirme la base destino de la recuperación de correo.', 1;

BEGIN TRANSACTION;
IF OBJECT_ID(N'Seguridad.SincronizacionProveedor', N'U') IS NULL
BEGIN
    CREATE TABLE Seguridad.SincronizacionProveedor (
        IdSincronizacion bigint IDENTITY PRIMARY KEY,
        UsuarioID int NOT NULL,
        Operacion varchar(20) NOT NULL,
        LlaveProveedor varchar(128) NOT NULL,
        Estado varchar(12) NOT NULL DEFAULT 'Pendiente',
        Intentos bigint NOT NULL DEFAULT 0,
        UltimoCodigoError varchar(60) NULL,
        FechaCreacion datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
        FechaUltimoIntento datetime2 NULL,
        FechaCompletado datetime2 NULL,
        CONSTRAINT CK_SincronizacionProveedor_Estado CHECK (Estado IN ('Pendiente','Completada','Fallida'))
    );
    CREATE UNIQUE INDEX UX_SincronizacionProveedor_EmailPendiente
        ON Seguridad.SincronizacionProveedor(UsuarioID)
        WHERE Operacion='Email' AND Estado='Pendiente';
END
ELSE IF COL_LENGTH(N'Seguridad.SincronizacionProveedor', N'LlaveProveedor') IS NULL
    THROW 57615, 'Existe un esquema de sincronización diferente. Revíselo antes de aplicar E1-04.', 1;
COMMIT TRANSACTION;

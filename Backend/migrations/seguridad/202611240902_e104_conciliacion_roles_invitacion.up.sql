SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57616, 'Confirme la base destino de E1-04.', 1;

BEGIN TRANSACTION;
IF OBJECT_ID(N'Seguridad.SincronizacionProveedor', N'U') IS NULL
    THROW 57616, 'Instale primero el diario de sincronización E1-04.', 1;
IF COL_LENGTH(N'Seguridad.SincronizacionProveedor', N'CorreoAlterno') IS NULL
    ALTER TABLE Seguridad.SincronizacionProveedor ADD CorreoAlterno nvarchar(320) NULL;
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'Seguridad.SincronizacionProveedor')
      AND name='UX_SincronizacionProveedor_UsuarioPendiente'
)
    CREATE UNIQUE INDEX UX_SincronizacionProveedor_UsuarioPendiente
        ON Seguridad.SincronizacionProveedor(UsuarioID) WHERE Estado='Pendiente';
COMMIT TRANSACTION;

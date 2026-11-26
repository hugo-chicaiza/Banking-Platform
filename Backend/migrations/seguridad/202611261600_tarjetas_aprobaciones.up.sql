/* E6-10: la aprobación de solicitudes de débito usa el permiso existente. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57720, 'Confirme la base destino de aprobaciones de tarjetas.', 1;
IF OBJECT_ID(N'Seguridad.TransaccionesInterfaz', N'U') IS NULL
   OR OBJECT_ID(N'Seguridad.SolicitudAprobacion', N'U') IS NULL
   OR OBJECT_ID(N'Auditoria.EventoPendiente', N'U') IS NULL
    THROW 57720, 'Faltan el catálogo, la cola o la auditoría de E0-08.', 1;

BEGIN TRANSACTION;
IF NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
               WHERE CodigoTransaccion = 'TAR-SOLICITAR')
    INSERT Seguridad.TransaccionesInterfaz
        (CodigoTransaccion, NombreTransaccion, Modulo, BaseObjetivo, RolesEjecucion, PermisoAprobacion, EsSensible, Estado)
    VALUES ('TAR-SOLICITAR', N'Aprobar o rechazar una solicitud de tarjeta de débito', 'Tarjetas',
            'cooperativa', N'["ADMIN","ASESOR"]', 'tar-solicitar:aprobar', 1, 'A');
IF NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WHERE CodigoTransaccion = 'TAR-SOLICITAR'
               AND BaseObjetivo = 'cooperativa' AND RolesEjecucion = N'["ADMIN","ASESOR"]'
               AND PermisoAprobacion = 'tar-solicitar:aprobar' AND EsSensible = 1 AND Estado = 'A')
    THROW 57720, 'La configuración de TAR-SOLICITAR es incompatible.', 1;
COMMIT TRANSACTION;

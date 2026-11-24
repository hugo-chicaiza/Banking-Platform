SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57614, 'Confirme la base destino de E1-04.', 1;

DECLARE @permiso nvarchar(128) =
    LTRIM(RTRIM(CONVERT(nvarchar(128), SESSION_CONTEXT(N'e104_permiso_aprobar_roles'))));
IF ISNULL(@permiso, N'') = N''
    THROW 57614, 'Falta el permiso institucional de aprobación E1-04.', 1;

BEGIN TRANSACTION;
IF EXISTS (
    SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoTransaccion = 'SEG-USUARIO-ROLES'
      AND (BaseObjetivo <> 'seguridad' OR RolesEjecucion <> N'["ADMIN"]'
           OR PermisoAprobacion <> @permiso OR EsSensible <> 1 OR Estado <> 'A')
)
    THROW 57614, 'La configuración existente de E1-04 es incompatible.', 1;

IF NOT EXISTS (
    SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoTransaccion = 'SEG-USUARIO-ROLES'
)
    INSERT INTO Seguridad.TransaccionesInterfaz
        (CodigoTransaccion, NombreTransaccion, Modulo, BaseObjetivo, RolesEjecucion,
         PermisoAprobacion, EsSensible, Estado)
    VALUES ('SEG-USUARIO-ROLES', N'Cambiar roles de un usuario', 'Seguridad', 'seguridad',
            N'["ADMIN"]', @permiso, 1, 'A');
COMMIT TRANSACTION;

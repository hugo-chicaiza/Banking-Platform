-- Ensayo local. Verifica y copia las asignaciones en una transacción que se revierte.
-- Ejecutar en BankingE305_Seguridad_Local con sqlcmd -S lpc:localhost -E -C -I -b.
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF DB_NAME() <> N'BankingE305_Seguridad_Local'
   OR ISNULL(CONVERT(nvarchar(40), CONNECTIONPROPERTY('net_transport')), N'') <> N'Shared memory'
    THROW 51404, 'El ensayo requiere la copia SQL local de Seguridad.', 1;

DECLARE @ahora datetime2 = CONVERT(datetime2, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time');
BEGIN TRY
    BEGIN TRANSACTION;

    SELECT c.IdUsuario, RTRIM(c.IdAgencia) AS IdAgencia, c.FechaInicio
    INTO #VigentesCaja
    FROM BankingE305_Cooperativa_Local.Caja.CajerosAsignadosAgencia c
    WHERE c.Estado = 1 AND c.FechaInicio <= @ahora
      AND (c.FechaFin IS NULL OR c.FechaFin >= @ahora);

    IF EXISTS (SELECT IdUsuario FROM #VigentesCaja GROUP BY IdUsuario HAVING COUNT(*) > 1)
        THROW 51404, 'Caja tiene usuarios con más de una asignación vigente.', 1;

    SELECT c.IdUsuario, c.IdAgencia AS AgenciaCaja, u.AgenciaID AS AgenciaSeguridad,
           CASE WHEN u.UsuarioID IS NULL THEN 'USUARIO_AUSENTE'
                WHEN ISNULL(u.RolesWorkOS, '') NOT LIKE '%CAJERO%' THEN 'USUARIO_SIN_ROL_CAJERO'
                ELSE 'ASIGNACION_DISTINTA' END AS Conflicto
    INTO #ConflictosCaja
    FROM #VigentesCaja c
    LEFT JOIN Organizacion.Usuarios u WITH (UPDLOCK, HOLDLOCK) ON u.UsuarioID = c.IdUsuario
    WHERE u.UsuarioID IS NULL
       OR ',' + ISNULL(u.RolesWorkOS, '') + ',' NOT LIKE '%,CAJERO,%'
       OR (u.AgenciaID IS NOT NULL AND u.AgenciaID <> TRY_CONVERT(int, c.IdAgencia))
       OR EXISTS (SELECT 1 FROM Organizacion.UsuarioAgencia a WITH (UPDLOCK, HOLDLOCK)
                  WHERE a.UsuarioID = c.IdUsuario
                    AND ((a.Activo = 1 AND a.IdAgencia <> c.IdAgencia)
                         OR (a.Activo = 0 AND a.IdAgencia = c.IdAgencia)));

    IF EXISTS (SELECT 1 FROM #ConflictosCaja)
    BEGIN
        SELECT Conflicto, COUNT_BIG(*) AS Cantidad FROM #ConflictosCaja GROUP BY Conflicto;
        THROW 51404, 'Resolver las diferencias entre Caja y Seguridad antes de migrar.', 1;
    END;

    DECLARE @cambios table (UsuarioID int, IdAgencia char(3), FechaUTC datetime2);
    INSERT Organizacion.UsuarioAgencia (UsuarioID, IdAgencia, Activo, FechaAsignacion, Origen)
    OUTPUT inserted.UsuarioID, inserted.IdAgencia, inserted.FechaAsignacion INTO @cambios
    SELECT c.IdUsuario, c.IdAgencia, 1,
           CONVERT(datetime2, c.FechaInicio AT TIME ZONE 'SA Pacific Standard Time' AT TIME ZONE 'UTC'),
           'Migracion'
    FROM #VigentesCaja c
    WHERE NOT EXISTS (SELECT 1 FROM Organizacion.UsuarioAgencia a WITH (UPDLOCK, HOLDLOCK)
                      WHERE a.UsuarioID = c.IdUsuario AND a.IdAgencia = c.IdAgencia);

    INSERT Organizacion.UsuarioAgenciaHistorial (UsuarioID, IdAgencia, Accion, PrincipalNueva, FechaUTC)
    SELECT UsuarioID, IdAgencia, 'MIGRACION', IdAgencia, FechaUTC FROM @cambios;

    UPDATE u SET AgenciaID = CONVERT(int, c.IdAgencia)
    FROM Organizacion.Usuarios u JOIN #VigentesCaja c ON c.IdUsuario = u.UsuarioID
    WHERE u.AgenciaID IS NULL;

    SELECT (SELECT COUNT_BIG(*) FROM #VigentesCaja) AS Verificadas,
           (SELECT COUNT_BIG(*) FROM @cambios) AS IncluidasEnEnsayo;
    ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

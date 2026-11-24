-- Ensayo local. Revierte por defecto. e104_aplicar_asignaciones=1 permite confirmar
-- exclusivamente en las copias SQL de laboratorio verificadas por este script.
-- El custodio de datos puede proporcionar las identidades verificadas en la misma
-- sesión, mediante #IdentidadesConfirmadas (IdUsuario int PRIMARY KEY, UsuarioID int).
-- La igualdad numérica por sí sola no acredita una identidad.
-- Ejecutar en BankingE305_Seguridad_Local con sqlcmd -S lpc:localhost -E -C -I -b.
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF DB_NAME() <> N'BankingE305_Seguridad_Local'
   OR ISNULL(CONVERT(nvarchar(40), CONNECTIONPROPERTY('net_transport')), N'') <> N'Shared memory'
    THROW 51404, 'El ensayo requiere la copia SQL local de Seguridad.', 1;

DECLARE @ahora datetime2 = CONVERT(datetime2, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time');
DECLARE @aplicar bit = ISNULL(TRY_CONVERT(bit, SESSION_CONTEXT(N'e104_aplicar_asignaciones')), 0);
IF OBJECT_ID('tempdb..#IdentidadesConfirmadas') IS NULL
    CREATE TABLE #IdentidadesConfirmadas (IdUsuario int PRIMARY KEY, UsuarioID int NOT NULL);

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
                WHEN ',' + ISNULL(u.RolesWorkOS, '') + ',' NOT LIKE '%,CAJERO,%'
                    THEN 'USUARIO_SIN_ROL_CAJERO'
                WHEN i.IdUsuario IS NULL OR i.UsuarioID <> c.IdUsuario
                    THEN 'IDENTIDAD_NO_CONFIRMADA'
                ELSE 'ASIGNACION_DISTINTA' END AS Conflicto
    INTO #ConflictosCaja
    FROM #VigentesCaja c
    LEFT JOIN Organizacion.Usuarios u WITH (UPDLOCK, HOLDLOCK) ON u.UsuarioID = c.IdUsuario
    LEFT JOIN #IdentidadesConfirmadas i ON i.IdUsuario = c.IdUsuario
    WHERE u.UsuarioID IS NULL
       OR ',' + ISNULL(u.RolesWorkOS, '') + ',' NOT LIKE '%,CAJERO,%'
       OR i.IdUsuario IS NULL OR i.UsuarioID <> c.IdUsuario
       OR (u.AgenciaID IS NOT NULL AND u.AgenciaID <> TRY_CONVERT(int, c.IdAgencia))
       OR EXISTS (SELECT 1 FROM Organizacion.UsuarioAgencia a WITH (UPDLOCK, HOLDLOCK)
                  WHERE a.UsuarioID = c.IdUsuario
                    AND ((a.Activo = 1 AND a.IdAgencia <> c.IdAgencia)
                         OR (a.Activo = 0 AND a.IdAgencia = c.IdAgencia)));

    IF EXISTS (SELECT 1 FROM #ConflictosCaja)
    BEGIN
        SELECT Conflicto, COUNT_BIG(*) AS Cantidad FROM #ConflictosCaja GROUP BY Conflicto;
        SELECT IdUsuario, AgenciaCaja, AgenciaSeguridad, Conflicto
        FROM #ConflictosCaja ORDER BY Conflicto, IdUsuario;
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

    IF EXISTS (
        SELECT 1 FROM #VigentesCaja c
        WHERE NOT EXISTS (
            SELECT 1 FROM Organizacion.UsuarioAgencia a
            WHERE a.UsuarioID = c.IdUsuario AND a.IdAgencia = c.IdAgencia AND a.Activo = 1
        )
    )
        THROW 51404, 'El destino no conserva todas las asignaciones vigentes.', 1;

    -- Conserva intervalos y metadatos históricos de las identidades verificadas.
    -- Una fila idéntica de origen se representa con su multiplicidad.
    IF OBJECT_ID(N'Organizacion.UsuarioAgenciaLegado', N'U') IS NULL
        CREATE TABLE Organizacion.UsuarioAgenciaLegado (
            Huella binary(32) NOT NULL PRIMARY KEY,
            UsuarioID int NOT NULL,
            DatosOrigen nvarchar(max) NOT NULL,
            Cantidad bigint NOT NULL
        );

    SELECT c.IdUsuario, j.DatosOrigen, HASHBYTES('SHA2_256', j.DatosOrigen) AS Huella,
           COUNT_BIG(*) AS Cantidad
    INTO #HistoricoCaja
    FROM BankingE305_Cooperativa_Local.Caja.CajerosAsignadosAgencia c
    JOIN #IdentidadesConfirmadas i ON i.IdUsuario = c.IdUsuario AND i.UsuarioID = c.IdUsuario
    CROSS APPLY (
        SELECT (SELECT c.* FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER) AS DatosOrigen
    ) j
    GROUP BY c.IdUsuario, j.DatosOrigen, HASHBYTES('SHA2_256', j.DatosOrigen);

    UPDATE destino SET Cantidad = origen.Cantidad
    FROM Organizacion.UsuarioAgenciaLegado destino
    JOIN #HistoricoCaja origen ON origen.Huella = destino.Huella;

    INSERT Organizacion.UsuarioAgenciaLegado (Huella, UsuarioID, DatosOrigen, Cantidad)
    SELECT h.Huella, h.IdUsuario, h.DatosOrigen, h.Cantidad
    FROM #HistoricoCaja h
    WHERE NOT EXISTS (SELECT 1 FROM Organizacion.UsuarioAgenciaLegado a WITH (UPDLOCK, HOLDLOCK)
                      WHERE a.Huella = h.Huella);

    SELECT (SELECT COUNT_BIG(*) FROM #VigentesCaja) AS Verificadas,
           (SELECT COUNT_BIG(*) FROM @cambios) AS IncluidasEnEnsayo,
           (SELECT COALESCE(SUM(Cantidad), 0) FROM #HistoricoCaja) AS IntervalosArchivados,
           (SELECT COALESCE(SUM(Cantidad), 0) FROM #HistoricoCaja
            WHERE JSON_VALUE(DatosOrigen, '$.FechaFin') IS NOT NULL) AS IntervalosCerrados;
    IF @aplicar = 1
    BEGIN
        DROP TABLE #HistoricoCaja, #ConflictosCaja, #VigentesCaja;
        COMMIT TRANSACTION;
    END
    ELSE ROLLBACK TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

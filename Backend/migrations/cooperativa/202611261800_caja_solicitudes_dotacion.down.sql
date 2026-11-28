SET XACT_ABORT ON;
IF COALESCE(CONVERT(sysname,SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57910,N'Confirme la base de la migración de solicitudes de dotación.',1;
BEGIN TRANSACTION;
IF OBJECT_ID(N'Caja.SolicitudDotacion',N'U') IS NOT NULL
BEGIN
    IF EXISTS (SELECT 1 FROM Caja.SolicitudDotacion WITH(TABLOCKX,HOLDLOCK))
        THROW 57911,N'Solicitudes existentes: preserve el historial de dotaciones.',1;
    DROP TABLE Caja.SolicitudDotacion;
END;
IF OBJECT_ID(N'Caja.FK_DotacionesCaja_Asiento_CAJ07', N'F') IS NOT NULL
BEGIN
    ALTER TABLE Caja.DotacionesCaja DROP CONSTRAINT FK_DotacionesCaja_Asiento_CAJ07;
    ALTER TABLE Caja.DotacionesCaja DROP COLUMN IdAsientoContable;
END;
COMMIT;

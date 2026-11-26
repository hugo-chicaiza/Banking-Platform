/* E6-10: registro duradero para publicar y conciliar la solicitud en SeguridadDB. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57720, 'Confirme la base destino de aprobaciones de tarjetas.', 1;
IF OBJECT_ID(N'Seguridad.AprobacionAplicada', N'U') IS NULL
   OR OBJECT_ID(N'Auditoria.EventoPendiente', N'U') IS NULL
   OR COL_LENGTH(N'Tarjeta.Tarjeta', N'SobreDescargadoEn') IS NULL
    THROW 57720, 'Faltan los objetos de E0-08 o la migración de débito de E6-10.', 1;

BEGIN TRANSACTION;
IF OBJECT_ID(N'Tarjeta.SolicitudAprobacionPendiente', N'U') IS NULL
BEGIN
    CREATE TABLE Tarjeta.SolicitudAprobacionPendiente (
        IdTarjeta int NOT NULL PRIMARY KEY REFERENCES Tarjeta.Tarjeta(IdTarjeta),
        IdOrganizacion varchar(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
        SolicitadoPor varchar(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
        NombreSolicitante nvarchar(150) NULL,
        IdInternoSolicitante int NOT NULL,
        RolesSolicitante nvarchar(200) NOT NULL CHECK (ISJSON(RolesSolicitante) = 1),
        IdAgencia char(3) NOT NULL CHECK (IdAgencia <> '000'),
        IdSolicitud bigint NULL,
        RevisadaEn datetime2(7) NULL,
        Conciliada bit NOT NULL DEFAULT 0
    );
    CREATE INDEX IX_TarjetaSolicitudAprobacionPendiente
        ON Tarjeta.SolicitudAprobacionPendiente (IdOrganizacion, RevisadaEn, IdTarjeta)
        WHERE Conciliada = 0;
END;
COMMIT TRANSACTION;

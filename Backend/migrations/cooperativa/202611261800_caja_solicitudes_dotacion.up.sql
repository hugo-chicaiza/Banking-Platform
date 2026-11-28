SET XACT_ABORT ON;
IF COALESCE(CONVERT(sysname,SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57910,N'Confirme la base de la migración de solicitudes de dotación.',1;
BEGIN TRANSACTION;
IF COL_LENGTH(N'Caja.DotacionesCaja', N'IdAsientoContable') IS NULL
    ALTER TABLE Caja.DotacionesCaja ADD IdAsientoContable int NULL
        CONSTRAINT FK_DotacionesCaja_Asiento_CAJ07
        REFERENCES Contabilidad.AsientoContable(IdAsientoContable);

IF OBJECT_ID(N'Caja.SolicitudDotacion',N'U') IS NULL
BEGIN
    CREATE TABLE Caja.SolicitudDotacion (
        IdSolicitud bigint IDENTITY PRIMARY KEY,
        IdJornada int NOT NULL REFERENCES Caja.JornadasCaja(IdJornadaCaja),
        IdBoveda int NOT NULL REFERENCES Boveda.Boveda(IdBoveda),
        IdAgencia char(3) NOT NULL REFERENCES Organizacion.Agencia(IdAgencia),
        IdFechaContable int NOT NULL REFERENCES Contabilidad.FechaContable(IdFechaContable),
        SolicitadoPor int NOT NULL,
        AutorizadoPor int NOT NULL,
        FechaSolicitud datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
        TipoDotacion varchar(10) NOT NULL CHECK (TipoDotacion IN ('INICIAL','ADICIONAL')),
        Desglose nvarchar(max) NOT NULL CHECK (ISJSON(Desglose)=1),
        Valores nvarchar(max) NOT NULL CHECK (ISJSON(Valores)=1),
        Monto decimal(18,2) NOT NULL CHECK (Monto>0),
        Observacion varchar(500) NULL,
        Clave varchar(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
        Huella char(64) NOT NULL,
        Estado varchar(10) NOT NULL DEFAULT 'PENDIENTE',
        ResueltoPor int NULL,
        FechaResolucion datetime2 NULL,
        Motivo varchar(500) NULL,
        IdDotacionCaja int NULL REFERENCES Caja.DotacionesCaja(IdDotacionCaja),
        BovedaBajoMinimo bit NULL,
        CONSTRAINT CK_SolicitudDotacion_DobleCustodia CHECK (AutorizadoPor<>SolicitadoPor),
        CONSTRAINT CK_SolicitudDotacion_Resolucion CHECK (
            (Estado='PENDIENTE' AND ResueltoPor IS NULL AND FechaResolucion IS NULL
                AND Motivo IS NULL AND IdDotacionCaja IS NULL AND BovedaBajoMinimo IS NULL)
            OR (Estado='CONFIRMADA' AND ResueltoPor IS NOT NULL AND ResueltoPor=AutorizadoPor
                AND FechaResolucion IS NOT NULL AND Motivo IS NULL AND IdDotacionCaja IS NOT NULL
                AND BovedaBajoMinimo IS NOT NULL)
            OR (Estado='RECHAZADA' AND ResueltoPor IS NOT NULL AND ResueltoPor=AutorizadoPor
                AND FechaResolucion IS NOT NULL AND Motivo IS NOT NULL AND LEN(LTRIM(RTRIM(Motivo)))>0
                AND IdDotacionCaja IS NULL AND BovedaBajoMinimo IS NULL)
        ),
        CONSTRAINT UQ_SolicitudDotacion_Clave UNIQUE(SolicitadoPor,Clave)
    );
    CREATE UNIQUE INDEX UX_SolicitudDotacion_Dotacion
        ON Caja.SolicitudDotacion(IdDotacionCaja) WHERE IdDotacionCaja IS NOT NULL;
    CREATE UNIQUE INDEX UX_SolicitudDotacion_InicialConfirmada
        ON Caja.SolicitudDotacion(IdJornada) WHERE Estado='CONFIRMADA' AND TipoDotacion='INICIAL';
    CREATE INDEX IX_SolicitudDotacion_Jornada
        ON Caja.SolicitudDotacion(IdJornada,IdSolicitud DESC);
END;
COMMIT;

SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57711, 'Falta confirmar la base destino de E1-11.', 1;
BEGIN TRANSACTION;
IF OBJECT_ID(N'Parametros.LimiteOperacion', N'U') IS NULL
BEGIN
    CREATE TABLE Parametros.LimiteOperacion (
        IdLimiteOperacion int IDENTITY PRIMARY KEY,
        CodigoTipoTransaccion varchar(30) NOT NULL
            REFERENCES Transacciones.TipoTransaccion(CodigoTipo),
        IdCanal int NOT NULL REFERENCES Canal.Canal(IdCanal),
        GrupoID int NULL,
        IdAgencia char(3) NULL REFERENCES Organizacion.Agencia(IdAgencia),
        MontoRequiereAprobacion decimal(18,2) NULL,
        MontoMaximoOperacion decimal(18,2) NULL,
        MontoMaximoDiario decimal(18,2) NULL,
        VigenciaDesde date NOT NULL,
        VigenciaHasta date NULL,
        Estado char(1) NOT NULL CONSTRAINT DF_LimiteOperacion_Estado DEFAULT 'A',
        IdSolicitud bigint NULL,
        CreadoPor int NULL,
        FechaCreacion datetime2 NOT NULL CONSTRAINT DF_LimiteOperacion_Fecha DEFAULT SYSUTCDATETIME(),
        CONSTRAINT CK_LimiteOperacion_Estado CHECK (Estado IN ('A','C')),
        CONSTRAINT CK_LimiteOperacion_Vigencia CHECK (VigenciaHasta >= VigenciaDesde),
        CONSTRAINT CK_LimiteOperacion_Montos CHECK (
            MontoRequiereAprobacion > 0 AND MontoMaximoOperacion > 0
            AND MontoMaximoDiario > 0 AND MontoRequiereAprobacion <= MontoMaximoOperacion
        )
    );
    CREATE INDEX IX_LimiteOperacion_Busqueda ON Parametros.LimiteOperacion
        (CodigoTipoTransaccion, IdCanal, VigenciaDesde);
END;
COMMIT TRANSACTION;

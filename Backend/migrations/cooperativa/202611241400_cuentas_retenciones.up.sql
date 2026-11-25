SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57650, 'Falta confirmar la base destino de E6-05.', 1;
BEGIN TRANSACTION;
DECLARE @fecha date=CONVERT(date,SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time');
IF EXISTS (
    SELECT 1
    FROM (VALUES ('CUENTAS_RETENCION','CAPITAL','RESTRINGIDO'),
                 ('CUENTAS_LIBERACION','RESTRINGIDO','CAPITAL')) v(Codigo,Debe,Haber)
    OUTER APPLY (
        SELECT TOP(1) p.IdPlantillaAsiento FROM Contabilidad.PlantillaAsiento p
        JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento=p.IdTipoAsiento
        WHERE p.CodigoPlantilla=v.Codigo AND p.Origen='CUENTAS' AND p.Estado=1
          AND t.EsManual=0 AND t.Estado='A' AND p.VigenciaDesde<=@fecha
          AND (p.VigenciaHasta IS NULL OR p.VigenciaHasta>=@fecha)
        ORDER BY p.VigenciaDesde DESC,p.Version DESC
    ) vigente
    WHERE vigente.IdPlantillaAsiento IS NULL OR (
        SELECT COUNT(*) FROM Contabilidad.PlantillaAsientoDetalle d
        WHERE d.IdPlantillaAsiento=vigente.IdPlantillaAsiento
    ) <> 2 OR EXISTS (
        SELECT lado,rol FROM (VALUES ('DEBITO',v.Debe),('CREDITO',v.Haber)) roles(lado,rol)
        EXCEPT
        SELECT d.TipoMovimiento,d.CodigoRol FROM Contabilidad.PlantillaAsientoDetalle d
        WHERE d.IdPlantillaAsiento=vigente.IdPlantillaAsiento AND d.OrigenCuenta='PRODUCTO'
          AND d.ComponenteImporte='PRINCIPAL' AND d.IdCuentaContable IS NULL
    )
)
    THROW 57650, 'Faltan las plantillas vigentes de retención y liberación de E4-01.', 1;

IF OBJECT_ID('Catalogo.TipoRetencion','U') IS NULL
    CREATE TABLE Catalogo.TipoRetencion (Codigo varchar(20) PRIMARY KEY, Nombre nvarchar(60) NOT NULL,
        Estado varchar(1) NOT NULL DEFAULT ('A') CHECK (Estado IN ('A','I')));
INSERT Catalogo.TipoRetencion (Codigo, Nombre)
SELECT v.Codigo,v.Nombre FROM (VALUES ('OrdenJudicial',N'Orden judicial'),
    ('GarantiaCredito',N'Garantía de crédito'),('Administrativa',N'Administrativa')) v(Codigo,Nombre)
WHERE NOT EXISTS (SELECT 1 FROM Catalogo.TipoRetencion t WHERE t.Codigo=v.Codigo);

IF OBJECT_ID('Cuentas.Retencion','U') IS NULL
BEGIN
    CREATE TABLE Cuentas.Retencion (
        IdRetencion bigint IDENTITY PRIMARY KEY,
        IdCuenta int NOT NULL REFERENCES Cuentas.Cuenta(IdCuenta),
        TipoRetencion varchar(20) NOT NULL REFERENCES Catalogo.TipoRetencion(Codigo),
        Monto decimal(18,2) NOT NULL,
        MontoSolicitado decimal(18,2) NOT NULL,
        ClaveEvento varchar(100) NOT NULL UNIQUE,
        ClaveLiberacion varchar(100) NULL,
        Motivo nvarchar(250) NOT NULL,
        DocumentoReferencia nvarchar(60) NOT NULL,
        Origen varchar(10) NOT NULL CHECK (Origen IN ('Manual','Modulo')),
        ModuloOrigen varchar(30) NULL,
        FechaInicio date NOT NULL,
        FechaFin date NULL,
        Estado varchar(12) NOT NULL CHECK (Estado IN ('Pendiente','Activa','Liberada','Ejecutada','Rechazada','Cancelada')),
        IdSolicitud bigint NULL,
        IdSolicitudLiberacion bigint NULL,
        IdAsiento int NULL REFERENCES Contabilidad.AsientoContable(IdAsientoContable),
        IdAsientoLiberacion int NULL REFERENCES Contabilidad.AsientoContable(IdAsientoContable),
        MotivoLiberacion nvarchar(250) NULL,
        CreadoPor int NOT NULL,
        FechaCreacion datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT CK_Retencion_Fechas CHECK (FechaFin IS NULL OR FechaFin >= FechaInicio),
        CONSTRAINT CK_Retencion_Monto CHECK ((Monto > 0 OR (Monto=0 AND TipoRetencion='OrdenJudicial'))
          AND MontoSolicitado > 0 AND MontoSolicitado >= Monto),
        CONSTRAINT CK_Retencion_Asiento CHECK ((Monto=0 AND IdAsiento IS NULL) OR (Monto>0 AND IdAsiento IS NOT NULL)),
        CONSTRAINT CK_Retencion_Modulo CHECK ((Origen='Manual' AND ModuloOrigen IS NULL)
          OR (Origen='Modulo' AND ModuloOrigen IS NOT NULL))
    );
    CREATE INDEX IX_Retencion_Cuenta ON Cuentas.Retencion(IdCuenta,Estado);
    CREATE INDEX IX_Retencion_Vencimiento ON Cuentas.Retencion(Estado,FechaFin,IdRetencion);
    CREATE UNIQUE INDEX UX_Retencion_Solicitud ON Cuentas.Retencion(IdSolicitud) WHERE IdSolicitud IS NOT NULL;
    CREATE UNIQUE INDEX UX_Retencion_Liberacion ON Cuentas.Retencion(ClaveLiberacion) WHERE ClaveLiberacion IS NOT NULL;
END;
EXEC(N'CREATE OR ALTER VIEW Cuentas.vw_RetenidoDescuadrado AS
    SELECT c.IdCuenta,c.SaldoRetenido,ISNULL(SUM(r.Monto),0) AS SumaRetenciones
    FROM Cuentas.Cuenta c LEFT JOIN Cuentas.Retencion r ON r.IdCuenta=c.IdCuenta AND r.Estado=''Activa''
    GROUP BY c.IdCuenta,c.SaldoRetenido HAVING c.SaldoRetenido<>ISNULL(SUM(r.Monto),0)');
COMMIT;

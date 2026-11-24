/* E5-03/E6-01: relación vigente y evidencia del autorizado de cuenta. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57503, 'Falta confirmar la base destino.', 1;
BEGIN TRANSACTION;
IF OBJECT_ID('Catalogo.TipoRelacionCliente','U') IS NULL
    CREATE TABLE Catalogo.TipoRelacionCliente (
        Codigo varchar(20) NOT NULL CONSTRAINT PK_TipoRelacionCliente PRIMARY KEY,
        Nombre nvarchar(60) NOT NULL, UnaVigente bit NOT NULL, RequiereSoporte bit NOT NULL,
        Estado char(1) NOT NULL CONSTRAINT DF_TipoRelacionCliente_Estado DEFAULT ('A')
    );
INSERT Catalogo.TipoRelacionCliente(Codigo,Nombre,UnaVigente,RequiereSoporte)
SELECT s.Codigo,s.Nombre,s.UnaVigente,s.RequiereSoporte
FROM (VALUES ('Tutor',N'Tutor',1,1),('RepresentanteLegal',N'Representante legal',1,1),
             ('Conyuge',N'Cónyuge',0,0),('Firmante',N'Firmante autorizado',0,1),
             ('Referencia',N'Referencia',0,0)) AS s(Codigo,Nombre,UnaVigente,RequiereSoporte)
WHERE NOT EXISTS (SELECT 1 FROM Catalogo.TipoRelacionCliente AS t WITH (UPDLOCK,HOLDLOCK) WHERE t.Codigo=s.Codigo);
IF OBJECT_ID('Clientes.ClienteRelacion','U') IS NULL
BEGIN
    CREATE TABLE Clientes.ClienteRelacion (
        IdRelacion int IDENTITY(1,1) NOT NULL CONSTRAINT PK_ClienteRelacion PRIMARY KEY,
        IdCliente int NOT NULL CONSTRAINT FK_ClienteRelacion_Cliente REFERENCES Clientes.Cliente(IdCliente),
        IdClienteRelacionado int NOT NULL CONSTRAINT FK_ClienteRelacion_Relacionado REFERENCES Clientes.Cliente(IdCliente),
        TipoRelacion varchar(20) NOT NULL CONSTRAINT FK_ClienteRelacion_Tipo REFERENCES Catalogo.TipoRelacionCliente(Codigo),
        FechaInicio date NOT NULL, FechaFin date NULL, IdArchivoSoporte bigint NULL,
        CreadoPor int NULL, FechaCreacion datetime2 NOT NULL CONSTRAINT DF_ClienteRelacion_Fecha DEFAULT SYSUTCDATETIME(),
        CONSTRAINT CK_ClienteRelacion_Distintos CHECK (IdCliente<>IdClienteRelacionado),
        CONSTRAINT CK_ClienteRelacion_Fechas CHECK (FechaFin IS NULL OR FechaFin>=FechaInicio)
    );
    CREATE UNIQUE INDEX UX_ClienteRelacion_UnaVigente
        ON Clientes.ClienteRelacion(IdCliente,TipoRelacion)
        WHERE FechaFin IS NULL AND TipoRelacion IN ('Tutor','RepresentanteLegal');
    CREATE INDEX IX_ClienteRelacion_Vigencia
        ON Clientes.ClienteRelacion(IdCliente,TipoRelacion,FechaInicio,FechaFin);
END
IF OBJECT_ID('Cuentas.CuentaAutorizado','U') IS NULL
BEGIN
    CREATE TABLE Cuentas.CuentaAutorizado (
        IdCuentaAutorizado int IDENTITY(1,1) NOT NULL CONSTRAINT PK_CuentaAutorizado PRIMARY KEY,
        IdCuenta int NOT NULL CONSTRAINT FK_CuentaAutorizado_Cuenta REFERENCES Cuentas.Cuenta(IdCuenta),
        IdClienteAutorizado int NOT NULL CONSTRAINT FK_CuentaAutorizado_Cliente REFERENCES Clientes.Cliente(IdCliente),
        Rol varchar(20) NOT NULL CONSTRAINT CK_CuentaAutorizado_Rol CHECK (Rol IN ('Tutor','RepresentanteLegal','Firmante')),
        IdClienteRelacion int NULL CONSTRAINT FK_CuentaAutorizado_Relacion REFERENCES Clientes.ClienteRelacion(IdRelacion),
        FechaInicio date NOT NULL, FechaFin date NULL,
        CONSTRAINT CK_CuentaAutorizado_Fechas CHECK (FechaFin IS NULL OR FechaFin>=FechaInicio)
    );
    CREATE UNIQUE INDEX UX_CuentaAutorizado_Vigente
        ON Cuentas.CuentaAutorizado(IdCuenta,IdClienteAutorizado,Rol) WHERE FechaFin IS NULL;
END
INSERT Parametros.Parametro(Clave,Modulo,Descripcion,TipoDato,Unidad,ValorMinimo,EsSensible)
SELECT 'CLI_EDAD_MAYORIA','Clientes',N'Edad de mayoría','Entero','años',1,1
WHERE NOT EXISTS(SELECT 1 FROM Parametros.Parametro WITH (UPDLOCK,HOLDLOCK) WHERE Clave='CLI_EDAD_MAYORIA');
INSERT Parametros.ParametroValor(IdParametro,Valor,VigenciaDesde,CreadoPor)
SELECT p.IdParametro,'18','20260101',NULL FROM Parametros.Parametro AS p
WHERE p.Clave='CLI_EDAD_MAYORIA'
  AND NOT EXISTS(SELECT 1 FROM Parametros.ParametroValor AS v WITH (UPDLOCK,HOLDLOCK) WHERE v.IdParametro=p.IdParametro);
COMMIT TRANSACTION;

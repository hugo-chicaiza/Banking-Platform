/* E5-08: catálogo y metadatos. El binario se guarda fuera de SQL. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de E5-08.', 1;

BEGIN TRANSACTION;
IF OBJECT_ID('Catalogo.ClaseDocumentoCliente', 'U') IS NULL
    CREATE TABLE Catalogo.ClaseDocumentoCliente (
        Codigo varchar(30) NOT NULL CONSTRAINT PK_ClaseDocumentoCliente PRIMARY KEY,
        Nombre nvarchar(80) NOT NULL,
        ObligatorioNatural bit NOT NULL,
        ObligatorioJuridico bit NOT NULL,
        Estado char(1) NOT NULL CONSTRAINT DF_ClaseDocumentoCliente_Estado DEFAULT ('A'),
        CONSTRAINT CK_ClaseDocumentoCliente_Estado CHECK (Estado IN ('A','I'))
    );

INSERT Catalogo.ClaseDocumentoCliente (Codigo,Nombre,ObligatorioNatural,ObligatorioJuridico)
SELECT v.Codigo,v.Nombre,v.Natural,v.Juridico
FROM (VALUES
    ('IDENTIDAD_ANVERSO',N'Documento de identidad (anverso)',1,0),
    ('IDENTIDAD_REVERSO',N'Documento de identidad (reverso)',1,0),
    ('CONSENTIMIENTO',N'Consentimiento firmado',1,1),
    ('RUC',N'RUC',0,1),
    ('NOMBRAMIENTO',N'Nombramiento del representante',0,1),
    ('FIRMA',N'Registro de firma',0,0),
    ('DOMICILIO',N'Comprobante de domicilio',0,0),
    ('OTRO',N'Otro',0,0)
) v(Codigo,Nombre,Natural,Juridico)
WHERE NOT EXISTS (SELECT 1 FROM Catalogo.ClaseDocumentoCliente c WHERE c.Codigo=v.Codigo);

IF OBJECT_ID('Clientes.ClienteArchivo', 'U') IS NULL
BEGIN
    CREATE TABLE Clientes.ClienteArchivo (
        IdArchivo bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_ClienteArchivo PRIMARY KEY,
        IdCliente int NOT NULL CONSTRAINT FK_ClienteArchivo_Cliente REFERENCES Clientes.Cliente (IdCliente),
        ClaseDocumento varchar(30) NOT NULL
            CONSTRAINT FK_ClienteArchivo_Clase REFERENCES Catalogo.ClaseDocumentoCliente (Codigo),
        ClaveAlmacenamiento varchar(200) NOT NULL CONSTRAINT UQ_ClienteArchivo_Clave UNIQUE,
        NombreOriginal nvarchar(150) NOT NULL,
        TipoContenido varchar(50) NOT NULL,
        TamanoBytes int NOT NULL,
        HashSha256 binary(32) NOT NULL,
        EstadoAnalisis varchar(12) NOT NULL CONSTRAINT DF_ClienteArchivo_Analisis DEFAULT ('Pendiente'),
        Version int NOT NULL CONSTRAINT DF_ClienteArchivo_Version DEFAULT (1),
        IdArchivoAnterior bigint NULL,
        Reemplazado bit NOT NULL CONSTRAINT DF_ClienteArchivo_Reemplazado DEFAULT (0),
        SubidoPor int NOT NULL,
        FechaSubida datetime2 NOT NULL CONSTRAINT DF_ClienteArchivo_Fecha DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UQ_ClienteArchivo_TitularClase UNIQUE (IdArchivo,IdCliente,ClaseDocumento),
        CONSTRAINT FK_ClienteArchivo_Anterior FOREIGN KEY (IdArchivoAnterior,IdCliente,ClaseDocumento)
            REFERENCES Clientes.ClienteArchivo (IdArchivo,IdCliente,ClaseDocumento),
        CONSTRAINT CK_ClienteArchivo_Tipo CHECK (TipoContenido IN ('application/pdf','image/jpeg','image/png')),
        CONSTRAINT CK_ClienteArchivo_Tamano CHECK (TamanoBytes BETWEEN 1 AND 5242880),
        CONSTRAINT CK_ClienteArchivo_Analisis CHECK (EstadoAnalisis IN ('Pendiente','Limpio','Rechazado')),
        CONSTRAINT CK_ClienteArchivo_Version CHECK (
            (Version=1 AND IdArchivoAnterior IS NULL)
            OR (Version>1 AND IdArchivoAnterior IS NOT NULL AND IdArchivoAnterior<IdArchivo)
        )
    );
    CREATE UNIQUE INDEX UX_ClienteArchivo_Sucesor ON Clientes.ClienteArchivo (IdArchivoAnterior)
        WHERE IdArchivoAnterior IS NOT NULL;
    CREATE INDEX IX_ClienteArchivo_Cliente ON Clientes.ClienteArchivo (IdCliente,ClaseDocumento,Reemplazado);
END;

INSERT Parametros.Parametro(Clave,Modulo,Descripcion,TipoDato,Unidad,ValorMinimo,ValorMaximo,EsSensible)
SELECT 'CLI_ARCHIVO_MAX_BYTES','Clientes',N'Tamaño máximo por archivo de cliente','Entero','bytes',1,5242880,1
WHERE NOT EXISTS(SELECT 1 FROM Parametros.Parametro WHERE Clave='CLI_ARCHIVO_MAX_BYTES');

INSERT Parametros.ParametroValor(IdParametro,Valor,VigenciaDesde,CreadoPor)
SELECT p.IdParametro,'5242880','20260101',NULL
FROM Parametros.Parametro p WHERE p.Clave='CLI_ARCHIVO_MAX_BYTES'
AND NOT EXISTS (SELECT 1 FROM Parametros.ParametroValor v WHERE v.IdParametro=p.IdParametro);
COMMIT TRANSACTION;

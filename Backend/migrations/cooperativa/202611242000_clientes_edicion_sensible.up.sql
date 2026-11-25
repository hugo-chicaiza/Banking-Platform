/* E5-04: correos secundarios, marca de verificado e historial con antes/después y solicitud. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57504, 'Falta confirmar la base destino de E5-04.', 1;

BEGIN TRANSACTION;
IF OBJECT_ID(N'Clientes.ClienteEmail', N'U') IS NULL
    CREATE TABLE Clientes.ClienteEmail (
        IdClienteEmail    int IDENTITY(1,1) NOT NULL CONSTRAINT PK_ClienteEmail PRIMARY KEY,
        IdCliente         int          NOT NULL
            CONSTRAINT FK_ClienteEmail_Cliente REFERENCES Clientes.Cliente (IdCliente),
        Email             varchar(150) NOT NULL,
        Etiqueta          varchar(30)  NOT NULL,
        Estado            char(1)      NOT NULL CONSTRAINT DF_ClienteEmail_Estado DEFAULT ('A'),
        VerificadoPor     int          NULL,
        FechaVerificacion datetime2(3) NULL,
        CreadoPor         int          NOT NULL,
        FechaCreacion     datetime2(3) NOT NULL CONSTRAINT DF_ClienteEmail_Fecha DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT CK_ClienteEmail_Minusculas CHECK (Email = LOWER(Email) COLLATE Latin1_General_CS_AS),
        CONSTRAINT CK_ClienteEmail_Estado CHECK (Estado IN ('A', 'I')),
        CONSTRAINT CK_ClienteEmail_Verificado CHECK ((VerificadoPor IS NULL AND FechaVerificacion IS NULL)
                                                OR (VerificadoPor IS NOT NULL AND FechaVerificacion IS NOT NULL))
    );
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_ClienteEmail_Activo'
               AND object_id = OBJECT_ID(N'Clientes.ClienteEmail'))
    CREATE UNIQUE INDEX UX_ClienteEmail_Activo ON Clientes.ClienteEmail (IdCliente, Email) WHERE Estado = 'A';

IF COL_LENGTH('Clientes.Cliente', 'EmailVerificadoPor') IS NULL
    ALTER TABLE Clientes.Cliente ADD EmailVerificadoPor int NULL, FechaEmailVerificado datetime2(3) NULL;

IF COL_LENGTH('Clientes.ClientesHis', 'IdSolicitud') IS NULL
    ALTER TABLE Clientes.ClientesHis ADD
        IdSolicitud   bigint       NULL,
        ValorAnterior varchar(500) NULL,
        ValorNuevo    varchar(500) NULL;

INSERT Parametros.Parametro (Clave, Modulo, Descripcion, TipoDato, Unidad, ValorMinimo, ValorMaximo, EsSensible)
SELECT 'CLI_MAX_EMAILS_SECUNDARIOS', 'Clientes', N'Máximo de correos secundarios por cliente', 'Entero', 'correos', 0, 10, 1
WHERE NOT EXISTS (SELECT 1 FROM Parametros.Parametro WITH (UPDLOCK, HOLDLOCK)
                  WHERE Clave = 'CLI_MAX_EMAILS_SECUNDARIOS');
INSERT Parametros.ParametroValor (IdParametro, Valor, VigenciaDesde, CreadoPor)
SELECT p.IdParametro, '2', '20260101', NULL
FROM Parametros.Parametro AS p
WHERE p.Clave = 'CLI_MAX_EMAILS_SECUNDARIOS'
  AND NOT EXISTS (SELECT 1 FROM Parametros.ParametroValor AS v WITH (UPDLOCK, HOLDLOCK)
                  WHERE v.IdParametro = p.IdParametro);
COMMIT TRANSACTION;

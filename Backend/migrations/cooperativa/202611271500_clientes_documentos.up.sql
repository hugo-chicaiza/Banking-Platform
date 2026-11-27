CREATE TABLE Catalogo.TipoDocumentoIdentidad (
    Codigo varchar(10) NOT NULL PRIMARY KEY,
    Nombre nvarchar(80) NOT NULL,
    Algoritmo varchar(20) NOT NULL CHECK (Algoritmo IN ('EC_CEDULA', 'EC_RUC', 'NINGUNO')),
    PatronCaracteres varchar(20) NOT NULL CHECK (PatronCaracteres IN ('DIGITOS', 'ALFANUMERICO')),
    LongitudMinima tinyint NOT NULL,
    LongitudMaxima tinyint NOT NULL,
    AplicaNatural bit NOT NULL,
    AplicaJuridico bit NOT NULL,
    RequierePais bit NOT NULL,
    RequiereVencimiento bit NOT NULL,
    DigitoVerificadorBloquea bit NOT NULL DEFAULT 1,
    PermitePrincipal bit NOT NULL,
    AccionAlVencer varchar(10) NOT NULL CHECK (AccionAlVencer IN ('Avisar', 'Suspender')),
    Activo bit NOT NULL DEFAULT 1,
    Version rowversion,
    CHECK (LongitudMinima BETWEEN 1 AND LongitudMaxima AND LongitudMaxima <= 20)
);

INSERT INTO Catalogo.TipoDocumentoIdentidad
    (Codigo, Nombre, Algoritmo, PatronCaracteres, LongitudMinima, LongitudMaxima,
     AplicaNatural, AplicaJuridico, RequierePais, RequiereVencimiento, PermitePrincipal, AccionAlVencer)
VALUES
    ('CED', N'Cédula', 'EC_CEDULA', 'DIGITOS', 10, 10, 1, 0, 0, 0, 1, 'Avisar'),
    ('RUC', N'RUC', 'EC_RUC', 'DIGITOS', 13, 13, 1, 1, 0, 0, 1, 'Avisar'),
    ('PAS', N'Pasaporte', 'NINGUNO', 'ALFANUMERICO', 5, 20, 1, 0, 1, 1, 1, 'Avisar');

CREATE TABLE Clientes.ClienteDocumento (
    IdDocumento bigint IDENTITY NOT NULL PRIMARY KEY,
    IdCliente int NOT NULL REFERENCES Clientes.Cliente(IdCliente),
    TipoDocumento varchar(10) NOT NULL REFERENCES Catalogo.TipoDocumentoIdentidad(Codigo),
    Numero varchar(20) NOT NULL,
    CodigoPaisEmision char(3) NULL,
    FechaEmision date NULL,
    FechaVencimiento date NULL,
    Principal bit NOT NULL DEFAULT 0,
    Estado varchar(20) NOT NULL DEFAULT 'REGISTRADO'
        CHECK (Estado IN ('REGISTRADO', 'POR_CORREGIR', 'ANULADO')),
    Version rowversion,
    CHECK (FechaEmision IS NULL OR FechaVencimiento IS NULL OR FechaEmision <= FechaVencimiento)
);

CREATE UNIQUE INDEX UX_ClienteDocumento_Pasaporte
    ON Clientes.ClienteDocumento(TipoDocumento, CodigoPaisEmision, Numero)
    WHERE TipoDocumento = 'PAS';
CREATE UNIQUE INDEX UX_ClienteDocumento_Numero
    ON Clientes.ClienteDocumento(TipoDocumento, Numero) WHERE TipoDocumento <> 'PAS';
CREATE UNIQUE INDEX UX_ClienteDocumento_Principal
    ON Clientes.ClienteDocumento(IdCliente) WHERE Principal = 1;

INSERT INTO Clientes.ClienteDocumento(IdCliente, TipoDocumento, Numero, Principal)
SELECT IdCliente, CASE TipoDocumento WHEN 'C' THEN 'CED' WHEN 'R' THEN 'RUC' ELSE 'PAS' END,
       UPPER(LTRIM(RTRIM(Identificacion))), 1
FROM Clientes.Cliente
WHERE TipoDocumento IN ('C', 'R', 'P');

IF EXISTS (
    SELECT 1 FROM sys.key_constraints
    WHERE parent_object_id = OBJECT_ID('Clientes.Cliente') AND name = 'UQ_Cliente_Identificacion'
)
    ALTER TABLE Clientes.Cliente DROP CONSTRAINT UQ_Cliente_Identificacion;
ELSE IF EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('Clientes.Cliente') AND name = 'UQ_Cliente_Identificacion'
)
    DROP INDEX UQ_Cliente_Identificacion ON Clientes.Cliente;

ALTER TABLE Clientes.Cliente DROP CONSTRAINT IF EXISTS CK_Cliente_TipoDocumento, CK_Cliente_Identificacion;
ALTER TABLE Clientes.Cliente ALTER COLUMN Identificacion varchar(20) NOT NULL;

IF EXISTS (SELECT 1 FROM Clientes.ClienteDocumento) OR EXISTS (SELECT 1 FROM Clientes.Cliente)
    THROW 50042, 'La reversión requiere preservar los documentos registrados.', 1;

ALTER TABLE Clientes.Cliente ALTER COLUMN Identificacion varchar(13) NOT NULL;
ALTER TABLE Clientes.Cliente ADD CONSTRAINT UQ_Cliente_Identificacion UNIQUE (Identificacion);
ALTER TABLE Clientes.Cliente ADD CONSTRAINT CK_Cliente_TipoDocumento CHECK (TipoDocumento IN ('C', 'R', 'P'));
ALTER TABLE Clientes.Cliente ADD CONSTRAINT CK_Cliente_Identificacion CHECK (
    TipoDocumento = 'C' AND LEN(Identificacion) = 10 AND Identificacion NOT LIKE '%[^0-9]%'
    OR TipoDocumento = 'R' AND LEN(Identificacion) = 13 AND Identificacion NOT LIKE '%[^0-9]%'
        AND RIGHT(Identificacion, 3) = '001'
    OR TipoDocumento = 'P' AND LEN(Identificacion) BETWEEN 5 AND 13
        AND Identificacion NOT LIKE '%[^0-9A-Z]%'
);
DROP TABLE Clientes.ClienteDocumento;
DROP TABLE Catalogo.TipoDocumentoIdentidad;

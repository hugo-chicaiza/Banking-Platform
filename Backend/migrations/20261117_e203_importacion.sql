IF OBJECT_ID('Contabilidad.ImportacionCatalogo','U') IS NULL
CREATE TABLE Contabilidad.ImportacionCatalogo (
    IdImportacion int IDENTITY PRIMARY KEY,
    NombreArchivo nvarchar(200) NOT NULL,
    Revision nvarchar(max) NOT NULL CHECK (ISJSON(Revision)=1),
    Filas int NOT NULL,
    FilasError int NOT NULL,
    CargadoPor int NOT NULL,
    FechaCarga datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
    AplicadoPor int NULL,
    FechaAplicada datetime2 NULL,
    CONSTRAINT CK_ImportacionCatalogo_Aplicacion CHECK (
        (AplicadoPor IS NULL AND FechaAplicada IS NULL)
        OR (AplicadoPor IS NOT NULL AND FechaAplicada IS NOT NULL AND FilasError=0)
    )
);

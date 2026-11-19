-- Esquema E3-01 observado; fixture exclusivamente para SQL local aislado.
IF OBJECT_ID('ProductosFinancieros.ReglaNumeracion','U') IS NULL
CREATE TABLE ProductosFinancieros.ReglaNumeracion(
 IdReglaNumeracion int IDENTITY CONSTRAINT PK_E301_ReglaNumeracion PRIMARY KEY,
 IdSubProducto int NOT NULL REFERENCES ProductosFinancieros.SubProducto(IdSubProducto),
 Prefijo varchar(20) NOT NULL CHECK(LEN(LTRIM(RTRIM(Prefijo)))>0),
 LongitudSecuencia tinyint NOT NULL CHECK(LongitudSecuencia BETWEEN 1 AND 18),
 VigenciaDesde date NOT NULL,VigenciaHasta date NULL,
 CONSTRAINT CK_E301_ReglaNumeracion_Vigencia CHECK(VigenciaHasta IS NULL OR VigenciaHasta>=VigenciaDesde),
 Estado char(1) NOT NULL DEFAULT('A') CHECK(Estado IN('A','I')),
 FechaCreacion datetime2 NOT NULL DEFAULT(SYSUTCDATETIME()));
IF OBJECT_ID('ProductosFinancieros.SecuenciaCuenta','U') IS NULL
CREATE TABLE ProductosFinancieros.SecuenciaCuenta(
 IdReglaNumeracion int NOT NULL CONSTRAINT PK_E301_SecuenciaCuenta PRIMARY KEY REFERENCES ProductosFinancieros.ReglaNumeracion(IdReglaNumeracion),
 UltimoNumero bigint NOT NULL DEFAULT(0) CHECK(UltimoNumero>=0),
 FechaActualizacion datetime2 NOT NULL DEFAULT(SYSUTCDATETIME()));

/*
  E0-10 #351 | CooperativaDB
  Basado en 202611181011_agencias_version.up.sql de origin/develop (5a22b5b).
  Revise el servidor de la conexion en SSMS y ejecute el lote completo.
  Unico cambio persistente: agregar VersionFila rowversion NOT NULL si falta.
*/
SET XACT_ABORT ON;

IF DB_NAME() <> N'CooperativaDB'
    THROW 57351, 'Seleccione CooperativaDB antes de ejecutar este lote.', 1;

DECLARE @Agencia int = OBJECT_ID(N'Organizacion.Agencia', N'U');

IF @Agencia IS NULL
    THROW 57351, 'Falta Organizacion.Agencia o no es visible.', 1;

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = @Agencia AND name = N'VersionFila')
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = @Agencia AND name = N'VersionFila'
          AND system_type_id = 189 AND is_nullable = 0
    )
        THROW 57351, 'VersionFila existe con una definicion distinta a rowversion NOT NULL.', 1;
END
ELSE
BEGIN
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = @Agencia AND system_type_id = 189)
        THROW 57351, 'Agencia ya tiene otra columna rowversion. Revise el esquema.', 1;

    ALTER TABLE Organizacion.Agencia ADD VersionFila rowversion NOT NULL;
END;

SELECT DB_NAME() AS base, c.name AS columna, TYPE_NAME(c.system_type_id) AS tipo_sql,
       c.is_nullable AS admite_null
FROM sys.columns c
WHERE c.object_id = @Agencia AND c.name = N'VersionFila';

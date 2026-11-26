-- E4-03. Índice para verificar la versión realmente aplicada a un asiento.
SET XACT_ABORT ON;
IF COL_LENGTH('Contabilidad.AsientoContable','IdPlantillaAsiento') IS NULL
    THROW 57870, 'Aplicar el esquema AC-01 antes de instalar el índice.', 1;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('Contabilidad.AsientoContable')
      AND name = 'IX_AsientoContable_PlantillaAplicada'
)
    EXEC(N'CREATE INDEX IX_AsientoContable_PlantillaAplicada
           ON Contabilidad.AsientoContable (IdPlantillaAsiento)
           WHERE IdPlantillaAsiento IS NOT NULL;');

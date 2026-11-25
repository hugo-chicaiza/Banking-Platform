SET NOCOUNT ON;
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57660, 'Falta confirmar la base destino de E6-06.', 1;
BEGIN TRANSACTION;
DECLARE @plantilla int = (SELECT CONVERT(int,value) FROM sys.extended_properties
    WHERE class=0 AND name=N'E606_PlantillaReclasificacion');
IF @plantilla IS NOT NULL
BEGIN
    IF EXISTS (SELECT 1 FROM Contabilidad.AsientoContable WITH (UPDLOCK,HOLDLOCK)
               WHERE IdPlantillaAsiento=@plantilla)
        THROW 57660, 'La plantilla tiene asientos. Se conserva el historico.', 1;
    DELETE FROM Contabilidad.PlantillaAsientoDetalle WHERE IdPlantillaAsiento=@plantilla;
    DELETE FROM Contabilidad.PlantillaAsiento
    WHERE IdPlantillaAsiento=@plantilla AND CodigoPlantilla='CUENTAS_RECLASIFICACION';
    EXEC sys.sp_dropextendedproperty @name=N'E606_PlantillaReclasificacion';
END;
DECLARE @tipo int = (SELECT CONVERT(int,value) FROM sys.extended_properties
    WHERE class=0 AND name=N'E606_TipoReclasificacion');
IF @tipo IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM Contabilidad.PlantillaAsiento WHERE IdTipoAsiento=@tipo)
   AND NOT EXISTS (SELECT 1 FROM Contabilidad.AsientoContable WHERE IdTipoAsiento=@tipo)
BEGIN
    DELETE FROM Contabilidad.TiposAsiento WHERE IdTipoAsiento=@tipo AND Codigo='CUENTAS_RECLASIFICACION';
    EXEC sys.sp_dropextendedproperty @name=N'E606_TipoReclasificacion';
END;
DECLARE @concepto int = (SELECT CONVERT(int,value) FROM sys.extended_properties
    WHERE class=0 AND name=N'E606_ConceptoReclasificacion');
IF @concepto IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM Contabilidad.PlantillaAsiento WHERE IdConceptoContable=@concepto)
   AND NOT EXISTS (SELECT 1 FROM Contabilidad.AsientoContable WHERE IdConceptoContable=@concepto)
BEGIN
    DELETE FROM Contabilidad.ConceptoContable
    WHERE IdConceptoContable=@concepto AND CodigoConcepto='CTA_RECLASIFICACION';
    EXEC sys.sp_dropextendedproperty @name=N'E606_ConceptoReclasificacion';
END;
COMMIT TRANSACTION;

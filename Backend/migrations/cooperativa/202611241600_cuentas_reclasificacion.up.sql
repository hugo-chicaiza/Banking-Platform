SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57660, 'Falta confirmar la base destino de E6-06.', 1;

BEGIN TRANSACTION;
DECLARE @codigo varchar(30) = 'CUENTAS_RECLASIFICACION';
DECLARE @nombre nvarchar(80) = N'Reclasificación de capital por cambio de subproducto';
IF NOT EXISTS (SELECT 1 FROM Contabilidad.TiposAsiento WITH (UPDLOCK,HOLDLOCK) WHERE Codigo=@codigo)
BEGIN
    INSERT Contabilidad.TiposAsiento(Codigo,Nombre,Descripcion,EsManual,Estado)
    VALUES (@codigo,@nombre,@nombre,0,'A');
    DECLARE @tipo_creado int = CONVERT(int,SCOPE_IDENTITY());
    EXEC sys.sp_addextendedproperty @name=N'E606_TipoReclasificacion', @value=@tipo_creado;
END;
IF NOT EXISTS (SELECT 1 FROM Contabilidad.ConceptoContable WITH (UPDLOCK,HOLDLOCK) WHERE CodigoConcepto=@codigo)
BEGIN
    INSERT Contabilidad.ConceptoContable(CodigoConcepto,ConceptoDetalle,Estado)
    VALUES (@codigo,@nombre,'Activo');
    DECLARE @concepto_creado int = CONVERT(int,SCOPE_IDENTITY());
    EXEC sys.sp_addextendedproperty @name=N'E606_ConceptoReclasificacion', @value=@concepto_creado;
END;
DECLARE @tipo int = (SELECT IdTipoAsiento FROM Contabilidad.TiposAsiento WHERE Codigo=@codigo AND Estado='A' AND EsManual=0);
DECLARE @concepto int = (SELECT IdConceptoContable FROM Contabilidad.ConceptoContable WHERE CodigoConcepto=@codigo AND Estado='Activo');
IF @tipo IS NULL OR @concepto IS NULL
    THROW 57660, 'Tipo o concepto de reclasificacion no disponible.', 1;

IF NOT EXISTS (SELECT 1 FROM Contabilidad.PlantillaAsiento WITH (UPDLOCK,HOLDLOCK) WHERE CodigoPlantilla=@codigo)
BEGIN
    INSERT Contabilidad.PlantillaAsiento(CodigoPlantilla,IdConceptoContable,Origen,IdTipoAsiento,Nombre,Estado)
    VALUES (@codigo,@concepto,'CUENTAS',@tipo,@nombre,1);
    DECLARE @plantilla int = CONVERT(int,SCOPE_IDENTITY());
    INSERT Contabilidad.PlantillaAsientoDetalle
        (IdPlantillaAsiento,Orden,TipoMovimiento,OrigenCuenta,IdCuentaContable,CodigoRol,ComponenteImporte)
    VALUES (@plantilla,1,'DEBITO','PRODUCTO',NULL,'CAPITAL','PRINCIPAL'),
           (@plantilla,2,'CREDITO','CONTRAPRODUCTO',NULL,'CAPITAL','PRINCIPAL');
    EXEC sys.sp_addextendedproperty @name=N'E606_PlantillaReclasificacion', @value=@plantilla;
END;

DECLARE @inicial int = (SELECT IdPlantillaAsiento FROM Contabilidad.PlantillaAsiento
    WHERE CodigoPlantilla=@codigo AND Version=1 AND IdTipoAsiento=@tipo
      AND IdConceptoContable=@concepto AND Origen='CUENTAS');
IF @inicial IS NULL OR
   (SELECT COUNT(*) FROM Contabilidad.PlantillaAsientoDetalle WHERE IdPlantillaAsiento=@inicial) <> 2 OR EXISTS (
    SELECT e.Orden,e.Lado,e.Origen,e.Rol,e.Componente
    FROM (VALUES (1,'DEBITO','PRODUCTO','CAPITAL','PRINCIPAL'),
                 (2,'CREDITO','CONTRAPRODUCTO','CAPITAL','PRINCIPAL')) e(Orden,Lado,Origen,Rol,Componente)
    EXCEPT
    SELECT d.Orden,d.TipoMovimiento,d.OrigenCuenta,d.CodigoRol,d.ComponenteImporte
    FROM Contabilidad.PlantillaAsientoDetalle d
    WHERE d.IdPlantillaAsiento=@inicial AND d.IdCuentaContable IS NULL
)
    THROW 57660, 'La plantilla existente difiere de la matriz de reclasificacion.', 1;
COMMIT TRANSACTION;

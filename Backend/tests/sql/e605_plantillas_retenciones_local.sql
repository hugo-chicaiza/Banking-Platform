SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57650,'Falta confirmar la base destino de E6-05.',1;
BEGIN TRANSACTION;
DECLARE @tipos TABLE (Codigo varchar(50) PRIMARY KEY, Nombre varchar(100), Debe varchar(30), Haber varchar(30));
INSERT @tipos VALUES ('CUENTAS_RETENCION','Reclasificacion por retencion','CAPITAL','RESTRINGIDO'),
    ('CUENTAS_LIBERACION','Reclasificacion por liberacion','RESTRINGIDO','CAPITAL');
INSERT Contabilidad.TiposAsiento (Codigo,Nombre,Descripcion,EsManual,Estado)
SELECT v.Codigo,v.Nombre,v.Nombre,0,'A' FROM @tipos v
WHERE NOT EXISTS (SELECT 1 FROM Contabilidad.TiposAsiento t WITH (UPDLOCK,HOLDLOCK) WHERE t.Codigo=v.Codigo);
INSERT Contabilidad.ConceptoContable (CodigoConcepto,ConceptoDetalle,Estado)
SELECT v.Codigo,v.Nombre,'Activo' FROM @tipos v
WHERE NOT EXISTS (SELECT 1 FROM Contabilidad.ConceptoContable c WITH (UPDLOCK,HOLDLOCK) WHERE c.CodigoConcepto=v.Codigo);
DECLARE @nuevas TABLE (Id int PRIMARY KEY, Codigo varchar(50));
INSERT Contabilidad.PlantillaAsiento (CodigoPlantilla,IdConceptoContable,Origen,IdTipoAsiento,Nombre,Estado)
OUTPUT inserted.IdPlantillaAsiento,inserted.CodigoPlantilla INTO @nuevas
SELECT v.Codigo,c.IdConceptoContable,'CUENTAS',t.IdTipoAsiento,v.Nombre,1
FROM @tipos v JOIN Contabilidad.ConceptoContable c ON c.CodigoConcepto=v.Codigo
JOIN Contabilidad.TiposAsiento t ON t.Codigo=v.Codigo
WHERE NOT EXISTS (SELECT 1 FROM Contabilidad.PlantillaAsiento p WITH (UPDLOCK,HOLDLOCK) WHERE p.CodigoPlantilla=v.Codigo);
INSERT Contabilidad.PlantillaAsientoDetalle
    (IdPlantillaAsiento,Orden,TipoMovimiento,OrigenCuenta,IdCuentaContable,CodigoRol,ComponenteImporte)
SELECT n.Id,x.Orden,x.Lado,'PRODUCTO',NULL,x.Rol,'PRINCIPAL'
FROM @nuevas n JOIN @tipos v ON v.Codigo=n.Codigo
CROSS APPLY (VALUES (1,'DEBITO',v.Debe),(2,'CREDITO',v.Haber)) x(Orden,Lado,Rol);
COMMIT;

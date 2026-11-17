/* Matriz respaldada por #371, #380 y la semilla AC-01 revisada.
   Ejecutar después del corte E2-01 y de las migraciones del motor.
   Las familias AC-01 preexistentes con otra matriz requieren revisión. */
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE @Tipos TABLE (Codigo varchar(50) PRIMARY KEY, Nombre varchar(100),
        Concepto varchar(30), Origen varchar(30), Tipo varchar(50));
    INSERT @Tipos VALUES
        ('DOT_CAJA','Dotacion de boveda a caja','DOT_CAJA','CAJA','CAJA_DOTACION'),
        ('DEV_CAJA','Devolucion de caja a boveda','DEV_CAJA','CAJA','CAJA_DEVOLUCION'),
        ('DOT_ATM','Dotacion de ATM desde boveda','DOT_ATM','ATM','ATM_DOTACION'),
        ('CAJA_DEPOSITO','Deposito en ventanilla','DEP_EFECTIVO','CAJA','CAJA_DEPOSITO');
    DECLARE @Lineas TABLE (Codigo varchar(50), Orden smallint, Lado varchar(7),
        Origen varchar(15), Cuenta varchar(8), Rol varchar(30), Base varchar(30),
        PRIMARY KEY (Codigo,Orden));
    INSERT @Lineas VALUES
        ('DOT_CAJA',1,'DEBITO','FIJA','11010510',NULL,'PRINCIPAL'),
        ('DOT_CAJA',2,'CREDITO','FIJA','11010505',NULL,'PRINCIPAL'),
        ('DEV_CAJA',1,'DEBITO','FIJA','11010505',NULL,'PRINCIPAL'),
        ('DEV_CAJA',2,'CREDITO','FIJA','11010510',NULL,'PRINCIPAL'),
        ('DOT_ATM',1,'DEBITO','FIJA','11010515',NULL,'PRINCIPAL'),
        ('DOT_ATM',2,'CREDITO','FIJA','11010505',NULL,'PRINCIPAL'),
        ('CAJA_DEPOSITO',1,'DEBITO','FIJA','11010510',NULL,'PRINCIPAL'),
        ('CAJA_DEPOSITO',2,'CREDITO','PRODUCTO',NULL,'CAPITAL','PRINCIPAL'),
        ('CAJA_DEPOSITO',3,'DEBITO','PRODUCTO',NULL,'CAPITAL','COMISION'),
        ('CAJA_DEPOSITO',4,'CREDITO','COMISION',NULL,NULL,'COMISION');

    IF EXISTS (SELECT 1 FROM @Lineas l WHERE l.Cuenta IS NOT NULL AND
        (SELECT COUNT(*) FROM Contabilidad.CuentasContables c WITH (HOLDLOCK)
         WHERE c.CodigoCuenta=l.Cuenta AND c.Estado=1 AND c.EsImputable=1
           AND c.SoloAutomatica=1)<>1)
        THROW 56120,N'El corte E2-01 debe habilitar los auxiliares verificados.',1;

    INSERT Contabilidad.TiposAsiento (Codigo,Nombre,Descripcion,EsManual,Estado)
    SELECT p.Tipo,p.Nombre,p.Nombre,0,'A' FROM @Tipos p
    WHERE NOT EXISTS (SELECT 1 FROM Contabilidad.TiposAsiento t WITH (UPDLOCK,HOLDLOCK)
                      WHERE t.Codigo=p.Tipo);
    INSERT Contabilidad.ConceptoContable (CodigoConcepto,ConceptoDetalle,Estado)
    SELECT p.Concepto,p.Nombre,'Activo' FROM @Tipos p
    WHERE NOT EXISTS (SELECT 1 FROM Contabilidad.ConceptoContable c WITH (UPDLOCK,HOLDLOCK)
                      WHERE c.CodigoConcepto=p.Concepto);

    IF EXISTS (SELECT 1 FROM @Tipos p WHERE
        (SELECT COUNT(*) FROM Contabilidad.TiposAsiento t WHERE t.Codigo=p.Tipo)<>1 OR
        (SELECT COUNT(*) FROM Contabilidad.TiposAsiento t WHERE t.Codigo=p.Tipo AND t.Estado='A' AND t.EsManual=0)<>1 OR
        (SELECT COUNT(*) FROM Contabilidad.ConceptoContable c WHERE c.CodigoConcepto=p.Concepto)<>1 OR
        (SELECT COUNT(*) FROM Contabilidad.ConceptoContable c WHERE c.CodigoConcepto=p.Concepto AND c.Estado='Activo')<>1)
        THROW 56121,N'Tipos o conceptos ambiguos o inactivos.',1;

    DECLARE @Nuevas TABLE (Id int PRIMARY KEY,Codigo varchar(50));
    INSERT Contabilidad.PlantillaAsiento
        (CodigoPlantilla,IdConceptoContable,Origen,IdTipoAsiento,Nombre,Estado)
    OUTPUT inserted.IdPlantillaAsiento,inserted.CodigoPlantilla INTO @Nuevas
    SELECT p.Codigo,c.IdConceptoContable,p.Origen,t.IdTipoAsiento,p.Nombre,1
    FROM @Tipos p JOIN Contabilidad.ConceptoContable c ON c.CodigoConcepto=p.Concepto
    JOIN Contabilidad.TiposAsiento t ON t.Codigo=p.Tipo
    WHERE NOT EXISTS (SELECT 1 FROM Contabilidad.PlantillaAsiento x WITH (UPDLOCK,HOLDLOCK)
                      WHERE x.CodigoPlantilla=p.Codigo);

    INSERT Contabilidad.PlantillaAsientoDetalle
        (IdPlantillaAsiento,Orden,TipoMovimiento,OrigenCuenta,IdCuentaContable,CodigoRol,ComponenteImporte)
    SELECT n.Id,l.Orden,l.Lado,l.Origen,c.IdCuentaContable,l.Rol,l.Base
    FROM @Nuevas n JOIN @Lineas l ON l.Codigo=n.Codigo
    LEFT JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=l.Cuenta;

    IF EXISTS (
        SELECT 1 FROM @Tipos p
        LEFT JOIN Contabilidad.PlantillaAsiento a ON a.CodigoPlantilla=p.Codigo AND a.Version=1
        LEFT JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento=a.IdTipoAsiento
        LEFT JOIN Contabilidad.ConceptoContable c ON c.IdConceptoContable=a.IdConceptoContable
        WHERE a.IdPlantillaAsiento IS NULL OR a.Estado<>1 OR a.Origen<>p.Origen
           OR t.Codigo<>p.Tipo OR c.CodigoConcepto<>p.Concepto
           OR (SELECT COUNT(*) FROM Contabilidad.PlantillaAsientoDetalle d
               WHERE d.IdPlantillaAsiento=a.IdPlantillaAsiento)<>(SELECT COUNT(*) FROM @Lineas WHERE Codigo=p.Codigo)
           OR EXISTS (
               SELECT l.Orden,l.Lado,l.Origen,l.Cuenta,l.Rol,l.Base FROM @Lineas l WHERE l.Codigo=p.Codigo
               EXCEPT
               SELECT d.Orden,d.TipoMovimiento,d.OrigenCuenta,x.CodigoCuenta,d.CodigoRol,d.ComponenteImporte
               FROM Contabilidad.PlantillaAsientoDetalle d
               LEFT JOIN Contabilidad.CuentasContables x ON x.IdCuentaContable=d.IdCuentaContable
               WHERE d.IdPlantillaAsiento=a.IdPlantillaAsiento
           )
    ) THROW 56122,N'La version inicial difiere de la matriz verificada. Revisar el historico.',1;
    COMMIT;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK;
    THROW;
END CATCH;

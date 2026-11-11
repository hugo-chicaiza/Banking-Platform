-- Sentidos verificados contra los asientos 3, 9 y 121 del histórico.
-- Caja y ATM usan sus auxiliares internos de 110105 en el nuevo catálogo.
-- Resuelve los IDs por código y puede volver a ejecutarse sin reemplazar plantillas.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

DECLARE @Configuracion TABLE (
    Codigo varchar(50) PRIMARY KEY,
    Concepto varchar(30) NOT NULL,
    Origen varchar(30) NOT NULL,
    Tipo int NOT NULL,
    Nombre varchar(100) NOT NULL,
    Debe varchar(30) NOT NULL,
    Haber varchar(30) NOT NULL
);
INSERT INTO @Configuracion VALUES
    ('DEP_EFECTIVO_CAJA', 'DEP_EFECTIVO', 'CAJA', 3, 'Depósito en efectivo en ventanilla', '11010502', '210135'),
    ('RET_EFECTIVO_CAJA', 'RET_EFECTIVO', 'CAJA', 4, 'Retiro en efectivo en ventanilla', '210135', '11010502'),
    ('RET_EFECTIVO_ATM', 'RET_EFECTIVO', 'ATM', 16, 'Retiro de efectivo en ATM', '210135', '11010503');

DECLARE @Nuevas TABLE (Id int PRIMARY KEY, Codigo varchar(50) NOT NULL);

IF EXISTS (
    SELECT 1
    FROM @Configuracion AS p
    WHERE (SELECT COUNT(*) FROM Contabilidad.ConceptoContable WHERE CodigoConcepto COLLATE DATABASE_DEFAULT = p.Concepto) <> 1
       OR NOT EXISTS (SELECT 1 FROM Contabilidad.TiposAsiento WHERE IdTipoAsiento = p.Tipo)
       OR (SELECT COUNT(*) FROM Contabilidad.CuentasContables
           WHERE CodigoCuenta COLLATE DATABASE_DEFAULT = p.Debe AND Estado = 1 AND EsImputable = 1) <> 1
       OR (SELECT COUNT(*) FROM Contabilidad.CuentasContables
           WHERE CodigoCuenta COLLATE DATABASE_DEFAULT = p.Haber AND Estado = 1 AND EsImputable = 1) <> 1
)
    THROW 56100, N'La semilla requiere conceptos, tipos y cuentas imputables del catálogo de prueba.', 1;

INSERT INTO Contabilidad.PlantillaAsiento
    (CodigoPlantilla, IdConceptoContable, Origen, IdTipoAsiento, Nombre)
OUTPUT inserted.IdPlantillaAsiento, inserted.CodigoPlantilla INTO @Nuevas
SELECT p.Codigo, c.IdConceptoContable, p.Origen, p.Tipo, p.Nombre
FROM @Configuracion AS p
JOIN Contabilidad.ConceptoContable AS c ON c.CodigoConcepto COLLATE DATABASE_DEFAULT = p.Concepto
WHERE NOT EXISTS (
    SELECT 1 FROM Contabilidad.PlantillaAsiento WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoPlantilla COLLATE DATABASE_DEFAULT = p.Codigo
);

INSERT INTO Contabilidad.PlantillaAsientoDetalle
    (IdPlantillaAsiento, Orden, IdCuentaContable, TipoMovimiento, ComponenteImporte)
SELECT n.Id, l.Orden, c.IdCuentaContable, l.Lado, 'MONTO'
FROM @Nuevas AS n
JOIN @Configuracion AS p ON p.Codigo = n.Codigo
CROSS APPLY (VALUES (1, p.Debe, 'DEBITO'), (2, p.Haber, 'CREDITO')) AS l(Orden, Cuenta, Lado)
JOIN Contabilidad.CuentasContables AS c
    ON c.CodigoCuenta COLLATE DATABASE_DEFAULT = l.Cuenta AND c.Estado = 1 AND c.EsImputable = 1;

UPDATE p SET Estado = 1
FROM Contabilidad.PlantillaAsiento AS p
JOIN @Nuevas AS n ON n.Id = p.IdPlantillaAsiento;

IF EXISTS (
    SELECT 1
    FROM @Configuracion AS p
    JOIN Contabilidad.PlantillaAsiento AS a ON a.CodigoPlantilla COLLATE DATABASE_DEFAULT = p.Codigo
    JOIN Contabilidad.ConceptoContable AS c ON c.IdConceptoContable = a.IdConceptoContable
    WHERE c.CodigoConcepto COLLATE DATABASE_DEFAULT <> p.Concepto
       OR a.Origen COLLATE DATABASE_DEFAULT <> p.Origen
       OR a.IdTipoAsiento <> p.Tipo
       OR EXISTS (
           SELECT d.Orden, cc.CodigoCuenta COLLATE DATABASE_DEFAULT,
                  d.TipoMovimiento COLLATE DATABASE_DEFAULT,
                  d.ComponenteImporte COLLATE DATABASE_DEFAULT
           FROM Contabilidad.PlantillaAsientoDetalle AS d
           JOIN Contabilidad.CuentasContables AS cc ON cc.IdCuentaContable = d.IdCuentaContable
           WHERE d.IdPlantillaAsiento = a.IdPlantillaAsiento
           EXCEPT
           SELECT x.Orden, x.Cuenta, x.Lado, 'MONTO'
           FROM (VALUES (1, p.Debe, 'DEBITO'), (2, p.Haber, 'CREDITO')) AS x(Orden, Cuenta, Lado)
       )
       OR (SELECT COUNT(*) FROM Contabilidad.PlantillaAsientoDetalle
           WHERE IdPlantillaAsiento = a.IdPlantillaAsiento) <> 2
)
    THROW 56105, N'Ya existe una plantilla con configuración distinta. Revísela antes de reemplazarla.', 1;

COMMIT TRANSACTION;

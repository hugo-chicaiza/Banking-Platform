/* E2-01 #371. REVISAR y ejecutar en SSMS, CooperativaDB.
   SOLO ESTRUCTURA. No crea auxiliares, no cambia imputabilidad ni saldos.
   IdCuentaSuperior es el nombre REAL; CodigoElemento/TipoCuenta son calculadas.
   1/2/4/6/8/10 es almacenamiento; la regla de movimientos ordinarios es =8.
   No sustituye la carga oficial de las 1182 cuentas ni decide destinos de E9.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;
IF DB_NAME() <> N'CooperativaDB' AND DB_NAME() NOT LIKE N'CooperativaDB_E201_Lab[_]%'
    THROW 56300, N'Base fuera del alcance E2-01.', 1;
IF @@TRANCOUNT <> 0 THROW 56300, N'Ejecutar sin transaccion previa.', 1;
IF COL_LENGTH('Contabilidad.CuentasContables','IdCuentaSuperior') IS NULL
 OR COLUMNPROPERTY(OBJECT_ID('Contabilidad.CuentasContables'),'CodigoElemento','IsComputed')<>1
 OR COLUMNPROPERTY(OBJECT_ID('Contabilidad.CuentasContables'),'TipoCuenta','IsComputed')<>1
    THROW 56300, N'Esquema distinto del revisado: inspeccionar antes de continuar.', 1;
IF EXISTS (SELECT 1 FROM Contabilidad.CuentasContables
           WHERE LEN(CodigoCuenta) NOT IN (1,2,4,6,8,10)
              OR CodigoCuenta LIKE '%[^0-9]%' OR DATALENGTH(CodigoCuenta)<>LEN(CodigoCuenta))
    THROW 56301, N'Codigos incompatibles: no se recortan ni corrigen automaticamente.', 1;
BEGIN TRY
BEGIN TRANSACTION;
IF COL_LENGTH('Contabilidad.CuentasContables','Descripcion') IS NULL
    ALTER TABLE Contabilidad.CuentasContables ADD Descripcion varchar(250) NULL;
IF COL_LENGTH('Contabilidad.CuentasContables','SoloAutomatica') IS NULL
    ALTER TABLE Contabilidad.CuentasContables ADD SoloAutomatica bit NOT NULL
        CONSTRAINT DF_E201_SoloAutomatica DEFAULT(0) WITH VALUES;
IF COL_LENGTH('Contabilidad.CuentasContables','EsCatalogoRegulador') IS NULL
    ALTER TABLE Contabilidad.CuentasContables ADD EsCatalogoRegulador bit NOT NULL
        CONSTRAINT DF_E201_EsCatalogo DEFAULT(0) WITH VALUES;
IF COL_LENGTH('Contabilidad.CuentasContables','CreadoPor') IS NULL
    ALTER TABLE Contabilidad.CuentasContables ADD CreadoPor int NULL;
IF COL_LENGTH('Contabilidad.CuentasContables','ModificadoPor') IS NULL
    ALTER TABLE Contabilidad.CuentasContables ADD ModificadoPor int NULL;
IF COL_LENGTH('Contabilidad.CuentasContables','Nivel') IS NULL
    ALTER TABLE Contabilidad.CuentasContables ADD Nivel AS (CONVERT(tinyint,LEN(CodigoCuenta))) PERSISTED;
IF OBJECT_ID('Contabilidad.CK_E201_Codigo') IS NULL
    ALTER TABLE Contabilidad.CuentasContables WITH CHECK ADD CONSTRAINT CK_E201_Codigo
    CHECK (LEN(CodigoCuenta) IN (1,2,4,6,8,10)
       AND CodigoCuenta NOT LIKE '%[^0-9]%' AND DATALENGTH(CodigoCuenta)=LEN(CodigoCuenta));
COMMIT;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK;
 THROW;
END CATCH;

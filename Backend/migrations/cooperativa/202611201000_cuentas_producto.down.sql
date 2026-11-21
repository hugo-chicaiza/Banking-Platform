-- E3-05 #378 · reversa (solo fuera de producción). No borra auxiliares con movimientos.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57800,'Confirme la base destino de E3-05.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 DROP TRIGGER IF EXISTS ProductosFinancieros.trg_ProductoComision_NoCredito;
 DROP TRIGGER IF EXISTS ProductosFinancieros.trg_ProductoSeguro_SoloCredito;
 DROP TRIGGER IF EXISTS Transacciones.trg_ComisionValor_Norma;
 DROP TRIGGER IF EXISTS Transacciones.trg_Comisiones_Categoria;
 IF COL_LENGTH('Transacciones.Comisiones','Categoria') IS NOT NULL
 BEGIN
  EXEC sys.sp_executesql N'UPDATE Transacciones.Comisiones SET IdCuentaContableIngreso=NULL;
   UPDATE Transacciones.Comisiones SET Estado=''A'' WHERE CodigoComision=''REP-TDB'' AND Categoria=''BASICO'';';
  ALTER TABLE Transacciones.Comisiones DROP CONSTRAINT FK_Comisiones_Categoria, CK_Comisiones_ValorMaximo;
  ALTER TABLE Transacciones.Comisiones DROP COLUMN Categoria, ValorMaximo;
 END;
 DROP TABLE IF EXISTS Transacciones.CategoriaServicio;
 IF COL_LENGTH('Credito.Seguro','IdCuentaContable') IS NOT NULL
 BEGIN ALTER TABLE Credito.Seguro DROP CONSTRAINT FK_Seguro_Cuenta; ALTER TABLE Credito.Seguro DROP COLUMN IdCuentaContable; END;
 IF COL_LENGTH('Credito.Impuesto','IdCuentaContable') IS NOT NULL
 BEGIN ALTER TABLE Credito.Impuesto DROP CONSTRAINT FK_Impuesto_Cuenta; ALTER TABLE Credito.Impuesto DROP COLUMN IdCuentaContable; END;
 DROP TRIGGER IF EXISTS Contabilidad.trg_CuentaProducto_Reglas;
 DROP TABLE IF EXISTS Contabilidad.CuentaProducto;
 DROP TABLE IF EXISTS Contabilidad.ClaseCuentaProducto;
 DROP TABLE IF EXISTS Contabilidad.RolCuentaProducto;
 EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER Contabilidad.trg_MovimientosContables_NivelE201
ON Contabilidad.MovimientosContables AFTER INSERT AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM inserted i JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=i.IdCuentaContable
 WHERE LEN(c.CodigoCuenta)<>8
 AND E201.fn_LineaAutorizada(i.IdAsientoContable,i.IdCuentaContable,i.TipoMovimiento,i.Monto)=0)
  THROW 56311,N''Movimientos ordinarios solo en auxiliares de exactamente 8 digitos.'',1;
 IF EXISTS(SELECT 1 FROM inserted i
 JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=i.IdCuentaContable
 JOIN Contabilidad.AsientoContable a ON a.IdAsientoContable=i.IdAsientoContable
 JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento=a.IdTipoAsiento
 WHERE c.SoloAutomatica=1 AND t.EsManual=1
 AND E201.fn_LineaAutorizada(i.IdAsientoContable,i.IdCuentaContable,i.TipoMovimiento,i.Monto)=0)
  THROW 56312,N''Cuenta solo automatica: asiento manual sin autorizacion de reclasificacion.'',1;
END;';
 DECLARE @nuevas TABLE (Codigo varchar(30) PRIMARY KEY);
 INSERT @nuevas VALUES ('21013515'),('21013520'),('21013525'),('21011005'),('25059005'),('25059010'),('25059015'),('25909005'),('25909010'),('16909005');
 IF EXISTS(SELECT 1 FROM Contabilidad.CuentasContables c JOIN @nuevas n ON n.Codigo=c.CodigoCuenta
           WHERE c.Saldo<>0 OR EXISTS(SELECT 1 FROM Contabilidad.MovimientosContables m WHERE m.IdCuentaContable=c.IdCuentaContable))
  THROW 57800,'Un auxiliar de E3-05 ya tiene movimientos: no se revierte.',1;
 DELETE c FROM Contabilidad.CuentasContables c JOIN @nuevas n ON n.Codigo=c.CodigoCuenta;
 UPDATE p SET EsImputable=1 FROM Contabilidad.CuentasContables p
 WHERE p.CodigoCuenta IN ('210110','250590','259090','169090')
   AND NOT EXISTS(SELECT 1 FROM Contabilidad.CuentasContables h WHERE h.IdCuentaSuperior=p.IdCuentaContable);
 UPDATE Contabilidad.CuentasContables SET NombreCuenta='Ahorro a la vista persona natural' WHERE CodigoCuenta='21013505';
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;

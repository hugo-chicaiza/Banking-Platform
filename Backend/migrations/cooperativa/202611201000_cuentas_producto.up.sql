-- E3-05 #378 · Cuentas contables de los productos (plan v5 aprobado 2026-11-20).
-- Modelo: cuenta de control + subledger. Se registra en el último nivel (cuenta imputable
-- sin hijas: CUC sec. 7, "hasta un nivel de seis (6) dígitos"; los auxiliares de 8 son
-- opcionales). Solo se crean auxiliares para el capital de depósitos por producto y para
-- separar acreedores dentro de subcuentas "otras" del CUC.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57800,'Confirme la base destino de E3-05.',1;
BEGIN TRY
 BEGIN TRANSACTION;
 IF OBJECT_ID('ProductosFinancieros.TipoProducto','U') IS NULL OR OBJECT_ID('Credito.TipoCredito','U') IS NULL
    OR OBJECT_ID('Contabilidad.CuentasContables','U') IS NULL OR OBJECT_ID('Transacciones.Comisiones','U') IS NULL
  THROW 57800,'Faltan las tablas base de productos, crédito o contabilidad.',1;
 IF OBJECT_ID('Contabilidad.CuentaProducto','U') IS NOT NULL
  THROW 57800,'E3-05 ya está aplicada.',1;

 /* 1. Auxiliares nuevos (10). El padre deja de ser imputable: se verifica que no tenga movimientos ni saldo. */
 DECLARE @nuevas TABLE (Codigo varchar(30) PRIMARY KEY, Nombre varchar(150), Padre varchar(30), SoloAutomatica bit);
 INSERT @nuevas VALUES
  ('21013515','Ahorro Objetivo','210135',1),
  ('21013520','Ahorro Horizonte','210135',1),
  ('21013525','Ahorro Reserva','210135',1),
  ('21011005','Cuenta corriente','210110',1),
  ('25059005','Contribución SOLCA por pagar','250590',0),
  ('25059010','IVA por pagar','250590',0),
  ('25059015','Contribución al Seguro de Depósitos por pagar','250590',0),
  ('25909005','Primas de seguros por pagar','259090',0),
  ('25909010','Por pagar a redes de pago','259090',0),
  ('16909005','Por cobrar a redes de pago','169090',0);
 IF EXISTS(SELECT 1 FROM @nuevas n JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=n.Codigo)
  THROW 57800,'Un auxiliar de E3-05 ya existe: revisar antes de aplicar.',1;
 IF (SELECT COUNT(DISTINCT n.Padre) FROM @nuevas n JOIN Contabilidad.CuentasContables p ON p.CodigoCuenta=n.Padre)<>5
  THROW 57800,'Falta una subcuenta padre del CUC.',1;
 IF EXISTS(SELECT 1 FROM Contabilidad.CuentasContables p WHERE p.CodigoCuenta IN (SELECT Padre FROM @nuevas) AND p.EsImputable=1
           AND (p.Saldo<>0 OR EXISTS(SELECT 1 FROM Contabilidad.MovimientosContables m WHERE m.IdCuentaContable=p.IdCuentaContable)))
  THROW 57800,'Una subcuenta padre tiene movimientos o saldo: reclasificar antes de abrir auxiliares.',1;
 UPDATE Contabilidad.CuentasContables SET EsImputable=0, FechaModificacion=SYSUTCDATETIME()
 WHERE CodigoCuenta IN (SELECT Padre FROM @nuevas) AND EsImputable=1;
 -- CodigoElemento, TipoCuenta y Nivel son columnas calculadas a partir del código.
 INSERT Contabilidad.CuentasContables (CodigoCuenta,NombreCuenta,Naturaleza,IdCuentaSuperior,Estado,EsImputable,
        EsCuentaValuacion,SoloAutomatica,EsCatalogoRegulador)
 SELECT n.Codigo,n.Nombre,p.Naturaleza,p.IdCuentaContable,1,1,0,n.SoloAutomatica,0
 FROM @nuevas n JOIN Contabilidad.CuentasContables p ON p.CodigoCuenta=n.Padre;
 -- 21013505 pasa a ser el capital del producto AHO001 (persona jurídica conserva 21013510).
 UPDATE Contabilidad.CuentasContables SET NombreCuenta='Ahorro a la vista', FechaModificacion=SYSUTCDATETIME()
 WHERE CodigoCuenta='21013505';

 /* 2. Registro en el último nivel (D-17): una cuenta hoja, no solo de 8 dígitos. */
 EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER Contabilidad.trg_MovimientosContables_NivelE201
ON Contabilidad.MovimientosContables AFTER INSERT AS
BEGIN
 SET NOCOUNT ON;
 /* E3-05 (D-17): el CUC exige registrar hasta 6 dígitos y deja libres los auxiliares; se
    registra en la cuenta del último nivel de su rama (sin hijas), tenga 4, 6 u 8 dígitos. */
 IF EXISTS(SELECT 1 FROM inserted i JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=i.IdCuentaContable
 WHERE EXISTS(SELECT 1 FROM Contabilidad.CuentasContables h WHERE h.IdCuentaSuperior=c.IdCuentaContable)
 AND E201.fn_LineaAutorizada(i.IdAsientoContable,i.IdCuentaContable,i.TipoMovimiento,i.Monto)=0)
  THROW 56311,N''Movimientos ordinarios solo en cuentas del último nivel (sin cuentas hijas).'',1;
 IF EXISTS(SELECT 1 FROM inserted i
 JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=i.IdCuentaContable
 JOIN Contabilidad.AsientoContable a ON a.IdAsientoContable=i.IdAsientoContable
 JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento=a.IdTipoAsiento
 WHERE c.SoloAutomatica=1 AND t.EsManual=1
 AND E201.fn_LineaAutorizada(i.IdAsientoContable,i.IdCuentaContable,i.TipoMovimiento,i.Monto)=0)
  THROW 56312,N''Cuenta solo automatica: asiento manual sin autorizacion de reclasificacion.'',1;
END;';

 /* 3. Roles, clases (qué rol lleva cada tipo y bajo qué cuenta) y asignaciones. */
 CREATE TABLE Contabilidad.RolCuentaProducto (
  CodigoRol varchar(30) NOT NULL CONSTRAINT PK_RolCuentaProducto PRIMARY KEY,
  Nombre nvarchar(120) NOT NULL,
  Descripcion nvarchar(300) NULL,
  Estado char(1) NOT NULL CONSTRAINT DF_RolCuentaProducto_Estado DEFAULT('A'),
  CONSTRAINT CK_RolCuentaProducto_Codigo CHECK (CodigoRol NOT LIKE '%[^A-Z_]%'),
  CONSTRAINT CK_RolCuentaProducto_Estado CHECK (Estado IN ('A','I'))
 );
 CREATE TABLE Contabilidad.ClaseCuentaProducto (
  IdClase int IDENTITY(1,1) NOT NULL CONSTRAINT PK_ClaseCuentaProducto PRIMARY KEY,
  IdTipoProducto int NOT NULL CONSTRAINT FK_ClaseCuentaProducto_Tipo REFERENCES ProductosFinancieros.TipoProducto(IdTipoProducto),
  IdTipoCredito int NULL CONSTRAINT FK_ClaseCuentaProducto_TipoCredito REFERENCES Credito.TipoCredito(IdTipoCredito),
  CodigoRol varchar(30) NOT NULL CONSTRAINT FK_ClaseCuentaProducto_Rol REFERENCES Contabilidad.RolCuentaProducto(CodigoRol),
  Situacion varchar(12) NULL,
  Condicion varchar(15) NULL,
  Tramo tinyint NULL,
  CuentaBase varchar(30) NOT NULL,
  Nivel varchar(8) NOT NULL,
  Obligatorio bit NOT NULL,
  SoloConTasa bit NOT NULL CONSTRAINT DF_ClaseCuentaProducto_SoloConTasa DEFAULT(0),
  Orden smallint NOT NULL,
  Estado char(1) NOT NULL CONSTRAINT DF_ClaseCuentaProducto_Estado DEFAULT('A'),
  CONSTRAINT CK_ClaseCuentaProducto_Situacion CHECK (Situacion IS NULL OR Situacion IN ('POR_VENCER','NO_DEVENGA','VENCIDA')),
  CONSTRAINT CK_ClaseCuentaProducto_Condicion CHECK (Condicion IS NULL OR Condicion IN ('ORIGINAL','REFINANCIADA','REESTRUCTURADA')),
  CONSTRAINT CK_ClaseCuentaProducto_Tramo CHECK (Tramo IS NULL OR Tramo BETWEEN 1 AND 5),
  CONSTRAINT CK_ClaseCuentaProducto_Nivel CHECK (Nivel IN ('TIPO','PRODUCTO')),
  CONSTRAINT CK_ClaseCuentaProducto_Estado CHECK (Estado IN ('A','I')),
  CONSTRAINT CK_ClaseCuentaProducto_Base CHECK (CuentaBase NOT LIKE '%[^0-9]%' AND LEN(CuentaBase) BETWEEN 1 AND 30)
 );
 CREATE UNIQUE INDEX UX_ClaseCuentaProducto ON Contabilidad.ClaseCuentaProducto (IdTipoProducto,IdTipoCredito,CodigoRol,Situacion,Condicion,Tramo);
 CREATE TABLE Contabilidad.CuentaProducto (
  IdCuentaProducto int IDENTITY(1,1) NOT NULL CONSTRAINT PK_CuentaProducto PRIMARY KEY,
  IdClase int NOT NULL CONSTRAINT FK_CuentaProducto_Clase REFERENCES Contabilidad.ClaseCuentaProducto(IdClase),
  IdProducto int NULL CONSTRAINT FK_CuentaProducto_Producto REFERENCES ProductosFinancieros.Producto(IdProducto),
  IdSubProducto int NULL CONSTRAINT FK_CuentaProducto_SubProducto REFERENCES ProductosFinancieros.SubProducto(IdSubProducto),
  IdCuentaContable int NOT NULL CONSTRAINT FK_CuentaProducto_Cuenta REFERENCES Contabilidad.CuentasContables(IdCuentaContable),
  VigenciaDesde date NOT NULL,
  VigenciaHasta date NULL,
  Estado char(1) NOT NULL CONSTRAINT DF_CuentaProducto_Estado DEFAULT('A'),
  IdSolicitud bigint NULL,
  CreadoPor int NULL,
  FechaCreacion datetime2 NOT NULL CONSTRAINT DF_CuentaProducto_Fecha DEFAULT(SYSUTCDATETIME()),
  CONSTRAINT CK_CuentaProducto_Alcance CHECK (IdProducto IS NULL OR IdSubProducto IS NULL),
  CONSTRAINT CK_CuentaProducto_Vigencia CHECK (VigenciaHasta IS NULL OR VigenciaHasta >= VigenciaDesde),
  CONSTRAINT CK_CuentaProducto_Estado CHECK (Estado IN ('A','I'))
 );
 CREATE INDEX IX_CuentaProducto_Clase ON Contabilidad.CuentaProducto (IdClase,IdProducto,IdSubProducto,VigenciaDesde) INCLUDE (IdCuentaContable,VigenciaHasta,Estado);

 EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER Contabilidad.trg_CuentaProducto_Reglas ON Contabilidad.CuentaProducto
AFTER INSERT, UPDATE AS
BEGIN
 SET NOCOUNT ON;
 /* Alcance de cada fila: producto efectivo (el del subproducto) y su tipo. */
 DECLARE @a TABLE (IdCuentaProducto int PRIMARY KEY, IdClase int, IdProducto int, IdSubProducto int, IdCuentaContable int,
                   VigenciaDesde date, VigenciaHasta date, ProductoEfectivo int);
 INSERT @a SELECT i.IdCuentaProducto,i.IdClase,i.IdProducto,i.IdSubProducto,i.IdCuentaContable,i.VigenciaDesde,i.VigenciaHasta,
        COALESCE(i.IdProducto,s.IdProducto)
 FROM inserted i LEFT JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto=i.IdSubProducto WHERE i.Estado=''A'';
 IF EXISTS(SELECT 1 FROM @a a JOIN Contabilidad.ClaseCuentaProducto k ON k.IdClase=a.IdClase
           JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=a.IdCuentaContable
           WHERE c.Estado=0 OR c.EsImputable=0 OR LEFT(c.CodigoCuenta,LEN(k.CuentaBase))<>k.CuentaBase
              OR EXISTS(SELECT 1 FROM Contabilidad.CuentasContables h WHERE h.IdCuentaSuperior=c.IdCuentaContable))
  THROW 56401,N''CUENTA_NO_CORRESPONDE: la cuenta debe ser activa, imputable, del último nivel y de la rama del rol.'',1;
 IF EXISTS(SELECT 1 FROM @a a JOIN Contabilidad.ClaseCuentaProducto k ON k.IdClase=a.IdClase
           WHERE k.Nivel=''PRODUCTO'' AND a.ProductoEfectivo IS NULL)
  THROW 56402,N''ROL_POR_PRODUCTO: este rol se asigna a cada producto.'',1;
 IF EXISTS(SELECT 1 FROM @a a JOIN Contabilidad.ClaseCuentaProducto k ON k.IdClase=a.IdClase
           JOIN ProductosFinancieros.Producto p ON p.IdProducto=a.ProductoEfectivo
           JOIN ProductosFinancieros.TipoProducto tp ON tp.IdTipoProducto=p.IdTipoProducto
           JOIN ProductosFinancieros.TipoProducto tk ON tk.IdTipoProducto=k.IdTipoProducto
           WHERE NOT (p.IdTipoProducto=k.IdTipoProducto OR (tk.Codigo=''CREDITO'' AND tp.Codigo=''TARJETA'' AND a.IdSubProducto IS NOT NULL))
              OR (k.IdTipoCredito IS NOT NULL AND tp.Codigo=''CREDITO'' AND ISNULL(p.IdTipoCredito,0)<>k.IdTipoCredito))
  THROW 56403,N''ROL_NO_APLICA: el rol no corresponde al tipo del producto.'',1;
 IF EXISTS(SELECT 1 FROM @a a JOIN Contabilidad.CuentaProducto v ON v.IdClase=a.IdClase AND v.IdCuentaProducto<>a.IdCuentaProducto
           AND v.Estado=''A'' AND ISNULL(v.IdProducto,0)=ISNULL(a.IdProducto,0) AND ISNULL(v.IdSubProducto,0)=ISNULL(a.IdSubProducto,0)
           AND v.VigenciaDesde<=ISNULL(a.VigenciaHasta,''99991231'') AND a.VigenciaDesde<=ISNULL(v.VigenciaHasta,''99991231''))
  THROW 56404,N''VIGENCIA_SOLAPADA: ya hay una asignación vigente para ese rol y alcance.'',1;
 IF EXISTS(SELECT 1 FROM @a a JOIN Contabilidad.ClaseCuentaProducto k ON k.IdClase=a.IdClase AND k.CodigoRol=''CAPITAL''
           JOIN Contabilidad.CuentaProducto v ON v.IdCuentaContable=a.IdCuentaContable AND v.IdCuentaProducto<>a.IdCuentaProducto AND v.Estado=''A''
           JOIN Contabilidad.ClaseCuentaProducto kv ON kv.IdClase=v.IdClase AND kv.CodigoRol=''CAPITAL''
           LEFT JOIN ProductosFinancieros.SubProducto sv ON sv.IdSubProducto=v.IdSubProducto
           WHERE ISNULL(COALESCE(v.IdProducto,sv.IdProducto),0)<>ISNULL(a.ProductoEfectivo,0))
  THROW 56405,N''CUENTA_YA_ASIGNADA: el capital de un producto no se comparte con otro.'',1;
END;';

 INSERT Contabilidad.RolCuentaProducto (CodigoRol,Nombre,Descripcion) VALUES
  ('CAPITAL',N'Capital',N'Depósitos del socio o aportes (cuenta de control del producto)'),
  ('RESTRINGIDO',N'Depósitos restringidos',N'Montos retenidos sin libre disponibilidad (CUC 2105)'),
  ('INTERES_GASTO',N'Gasto de intereses',N'Intereses causados sobre depósitos (CUC 4101)'),
  ('INTERES_POR_PAGAR',N'Intereses por pagar',N'Intereses devengados no pagados (CUC 2501)'),
  ('INTERES_GASTO_RESTRINGIDO',N'Gasto de intereses de restringidos',N'CUC 410145'),
  ('INTERES_POR_PAGAR_RESTRINGIDO',N'Intereses por pagar de restringidos',N'CUC 250155'),
  ('DEPOSITO_NO_CUBIERTO',N'Depósitos no cubiertos por el Seguro de Depósitos',N'Cuenta de orden CUC 7404 (COMF art. 323)'),
  ('CONTRA_DEPOSITO_NO_CUBIERTO',N'Contrapartida de depósitos no cubiertos',N'CUC 7304'),
  ('CARTERA',N'Cartera de créditos',N'Por situación, condición y tramo de días (CUC grupo 14)'),
  ('INTERES_POR_COBRAR',N'Intereses por cobrar',N'CUC 1603'),
  ('INTERES_GANADO',N'Intereses ganados',N'CUC 5104'),
  ('INTERES_MORA',N'Interés de mora',N'CUC 510450'),
  ('PROVISION',N'Provisión de cartera',N'CUC 1499'),
  ('GASTO_PROVISION',N'Gasto de provisión',N'CUC 4402'),
  ('INTERES_SUSPENSO',N'Intereses en suspenso',N'Cuenta de orden CUC 7109'),
  ('CONTRA_INTERES_SUSPENSO',N'Contrapartida de intereses en suspenso',N'CUC 7209'),
  ('CASTIGO',N'Cartera castigada',N'Cuenta de orden CUC 7103'),
  ('CONTRA_CASTIGO',N'Contrapartida de cartera castigada',N'CUC 7203'),
  ('RECUPERACION_CASTIGO',N'Recuperación de cartera castigada',N'CUC 560405'),
  ('APROBADO_NO_DESEMBOLSADO',N'Créditos aprobados no desembolsados',N'Contingente CUC 6404'),
  ('CONTRA_NO_DESEMBOLSADO',N'Contrapartida de aprobados no desembolsados',N'CUC 6304'),
  ('CUPO_NO_UTILIZADO',N'Cupo de tarjeta no utilizado',N'CUC 6404: cupo extendido a tarjetahabientes'),
  ('CONTRA_CUPO_NO_UTILIZADO',N'Contrapartida del cupo no utilizado',N'CUC 6304');

 DECLARE @clases TABLE (Tipo varchar(25), TipoCredito varchar(20), Rol varchar(30), Situacion varchar(12), Condicion varchar(15),
                        Tramo tinyint, Base varchar(30), Nivel varchar(8), Obligatorio bit, SoloConTasa bit, Orden smallint);
 INSERT @clases VALUES
  ('CUENTA_AHORRO',NULL,'CAPITAL',NULL,NULL,NULL,'210135','PRODUCTO',1,0,10),
  ('CUENTA_AHORRO',NULL,'RESTRINGIDO',NULL,NULL,NULL,'2105','TIPO',1,0,20),
  ('CUENTA_AHORRO',NULL,'INTERES_GASTO',NULL,NULL,NULL,'410115','TIPO',1,1,30),
  ('CUENTA_AHORRO',NULL,'INTERES_POR_PAGAR',NULL,NULL,NULL,'250105','TIPO',1,1,40),
  ('CUENTA_AHORRO',NULL,'INTERES_GASTO_RESTRINGIDO',NULL,NULL,NULL,'410145','TIPO',1,1,50),
  ('CUENTA_AHORRO',NULL,'INTERES_POR_PAGAR_RESTRINGIDO',NULL,NULL,NULL,'250155','TIPO',1,1,60),
  ('CUENTA_AHORRO',NULL,'DEPOSITO_NO_CUBIERTO',NULL,NULL,NULL,'740405','TIPO',1,0,70),
  ('CUENTA_AHORRO',NULL,'CONTRA_DEPOSITO_NO_CUBIERTO',NULL,NULL,NULL,'7304','TIPO',1,0,80),
  ('CUENTA_CORRIENTE',NULL,'CAPITAL',NULL,NULL,NULL,'210110','PRODUCTO',1,0,10),
  ('CUENTA_CORRIENTE',NULL,'RESTRINGIDO',NULL,NULL,NULL,'2105','TIPO',1,0,20),
  ('CUENTA_CORRIENTE',NULL,'INTERES_GASTO',NULL,NULL,NULL,'410105','TIPO',1,1,30),
  ('CUENTA_CORRIENTE',NULL,'INTERES_POR_PAGAR',NULL,NULL,NULL,'250105','TIPO',1,1,40),
  ('CUENTA_CORRIENTE',NULL,'INTERES_GASTO_RESTRINGIDO',NULL,NULL,NULL,'410145','TIPO',1,1,50),
  ('CUENTA_CORRIENTE',NULL,'INTERES_POR_PAGAR_RESTRINGIDO',NULL,NULL,NULL,'250155','TIPO',1,1,60),
  ('CUENTA_CORRIENTE',NULL,'DEPOSITO_NO_CUBIERTO',NULL,NULL,NULL,'740405','TIPO',1,0,70),
  ('CUENTA_CORRIENTE',NULL,'CONTRA_DEPOSITO_NO_CUBIERTO',NULL,NULL,NULL,'7304','TIPO',1,0,80),
  ('CERTIFICADO_APORTACION',NULL,'CAPITAL',NULL,NULL,NULL,'3103','TIPO',1,0,10),
  ('TARJETA',NULL,'CUPO_NO_UTILIZADO',NULL,NULL,NULL,'640410','TIPO',0,0,10),
  ('TARJETA',NULL,'CONTRA_CUPO_NO_UTILIZADO',NULL,NULL,NULL,'6304','TIPO',0,0,20);
 -- Crédito: cartera por condición × situación × tramo, y el resto por condición (CUC grupo 14, 1603, 5104, 1499).
 DECLARE @grupos TABLE (TipoCredito varchar(20), Condicion varchar(15), Situacion varchar(12), Grupo char(4), Orden smallint);
 INSERT @grupos VALUES
  ('CONSUMO','ORIGINAL','POR_VENCER','1402',100),('CONSUMO','ORIGINAL','NO_DEVENGA','1426',110),('CONSUMO','ORIGINAL','VENCIDA','1450',120),
  ('CONSUMO','REFINANCIADA','POR_VENCER','1410',130),('CONSUMO','REFINANCIADA','NO_DEVENGA','1434',140),('CONSUMO','REFINANCIADA','VENCIDA','1458',150),
  ('CONSUMO','REESTRUCTURADA','POR_VENCER','1418',160),('CONSUMO','REESTRUCTURADA','NO_DEVENGA','1442',170),('CONSUMO','REESTRUCTURADA','VENCIDA','1466',180),
  ('MICRO','ORIGINAL','POR_VENCER','1404',100),('MICRO','ORIGINAL','NO_DEVENGA','1428',110),('MICRO','ORIGINAL','VENCIDA','1452',120),
  ('MICRO','REFINANCIADA','POR_VENCER','1412',130),('MICRO','REFINANCIADA','NO_DEVENGA','1436',140),('MICRO','REFINANCIADA','VENCIDA','1460',150),
  ('MICRO','REESTRUCTURADA','POR_VENCER','1420',160),('MICRO','REESTRUCTURADA','NO_DEVENGA','1444',170),('MICRO','REESTRUCTURADA','VENCIDA','1468',180);
 INSERT @clases
 SELECT 'CREDITO',g.TipoCredito,'CARTERA',g.Situacion,g.Condicion,t.n,g.Grupo+RIGHT('0'+CONVERT(varchar(2),t.n*5),2),'TIPO',1,0,g.Orden+t.n
 FROM @grupos g CROSS JOIN (VALUES(1),(2),(3),(4),(5)) t(n);
 INSERT @clases VALUES
  ('CREDITO','CONSUMO','INTERES_POR_COBRAR',NULL,'ORIGINAL',NULL,'160310','TIPO',1,0,200),
  ('CREDITO','CONSUMO','INTERES_POR_COBRAR',NULL,'REFINANCIADA',NULL,'160345','TIPO',1,0,201),
  ('CREDITO','CONSUMO','INTERES_POR_COBRAR',NULL,'REESTRUCTURADA',NULL,'160350','TIPO',1,0,202),
  ('CREDITO','CONSUMO','INTERES_GANADO',NULL,'ORIGINAL',NULL,'510410','TIPO',1,0,210),
  ('CREDITO','CONSUMO','INTERES_GANADO',NULL,'REFINANCIADA',NULL,'510430','TIPO',1,0,211),
  ('CREDITO','CONSUMO','INTERES_GANADO',NULL,'REESTRUCTURADA',NULL,'510435','TIPO',1,0,212),
  ('CREDITO','CONSUMO','PROVISION',NULL,'ORIGINAL',NULL,'149910','TIPO',1,0,220),
  ('CREDITO','CONSUMO','PROVISION',NULL,'REFINANCIADA',NULL,'149945','TIPO',1,0,221),
  ('CREDITO','CONSUMO','PROVISION',NULL,'REESTRUCTURADA',NULL,'149950','TIPO',1,0,222),
  ('CREDITO','CONSUMO','INTERES_MORA',NULL,NULL,NULL,'510450','TIPO',1,0,230),
  ('CREDITO','CONSUMO','GASTO_PROVISION',NULL,NULL,NULL,'440220','TIPO',1,0,240),
  ('CREDITO','CONSUMO','INTERES_SUSPENSO',NULL,NULL,NULL,'710910','TIPO',1,0,250),
  ('CREDITO','CONSUMO','CONTRA_INTERES_SUSPENSO',NULL,NULL,NULL,'7209','TIPO',1,0,251),
  ('CREDITO','CONSUMO','CASTIGO',NULL,NULL,NULL,'710310','TIPO',1,0,260),
  ('CREDITO','CONSUMO','CONTRA_CASTIGO',NULL,NULL,NULL,'7203','TIPO',1,0,261),
  ('CREDITO','CONSUMO','RECUPERACION_CASTIGO',NULL,NULL,NULL,'560405','TIPO',1,0,262),
  ('CREDITO','CONSUMO','APROBADO_NO_DESEMBOLSADO',NULL,NULL,NULL,'640410','TIPO',1,0,270),
  ('CREDITO','CONSUMO','CONTRA_NO_DESEMBOLSADO',NULL,NULL,NULL,'6304','TIPO',1,0,271),
  ('CREDITO','MICRO','INTERES_POR_COBRAR',NULL,'ORIGINAL',NULL,'160320','TIPO',1,0,200),
  ('CREDITO','MICRO','INTERES_POR_COBRAR',NULL,'REFINANCIADA',NULL,'160345','TIPO',1,0,201),
  ('CREDITO','MICRO','INTERES_POR_COBRAR',NULL,'REESTRUCTURADA',NULL,'160350','TIPO',1,0,202),
  ('CREDITO','MICRO','INTERES_GANADO',NULL,'ORIGINAL',NULL,'510420','TIPO',1,0,210),
  ('CREDITO','MICRO','INTERES_GANADO',NULL,'REFINANCIADA',NULL,'510430','TIPO',1,0,211),
  ('CREDITO','MICRO','INTERES_GANADO',NULL,'REESTRUCTURADA',NULL,'510435','TIPO',1,0,212),
  ('CREDITO','MICRO','PROVISION',NULL,'ORIGINAL',NULL,'149920','TIPO',1,0,220),
  ('CREDITO','MICRO','PROVISION',NULL,'REFINANCIADA',NULL,'149945','TIPO',1,0,221),
  ('CREDITO','MICRO','PROVISION',NULL,'REESTRUCTURADA',NULL,'149950','TIPO',1,0,222),
  ('CREDITO','MICRO','INTERES_MORA',NULL,NULL,NULL,'510450','TIPO',1,0,230),
  ('CREDITO','MICRO','GASTO_PROVISION',NULL,NULL,NULL,'440240','TIPO',1,0,240),
  ('CREDITO','MICRO','INTERES_SUSPENSO',NULL,NULL,NULL,'710920','TIPO',1,0,250),
  ('CREDITO','MICRO','CONTRA_INTERES_SUSPENSO',NULL,NULL,NULL,'7209','TIPO',1,0,251),
  ('CREDITO','MICRO','CASTIGO',NULL,NULL,NULL,'710310','TIPO',1,0,260),
  ('CREDITO','MICRO','CONTRA_CASTIGO',NULL,NULL,NULL,'7203','TIPO',1,0,261),
  ('CREDITO','MICRO','RECUPERACION_CASTIGO',NULL,NULL,NULL,'560405','TIPO',1,0,262),
  ('CREDITO','MICRO','APROBADO_NO_DESEMBOLSADO',NULL,NULL,NULL,'640420','TIPO',1,0,270),
  ('CREDITO','MICRO','CONTRA_NO_DESEMBOLSADO',NULL,NULL,NULL,'6304','TIPO',1,0,271);
 IF EXISTS(SELECT 1 FROM @clases k WHERE NOT EXISTS(SELECT 1 FROM Contabilidad.CuentasContables c WHERE c.CodigoCuenta=k.Base AND c.Estado=1))
  THROW 57800,'Una cuenta base del CUC no existe o está inactiva.',1;
 IF EXISTS(SELECT 1 FROM @clases k WHERE NOT EXISTS(SELECT 1 FROM ProductosFinancieros.TipoProducto t WHERE t.Codigo=k.Tipo)
           OR (k.TipoCredito IS NOT NULL AND NOT EXISTS(SELECT 1 FROM Credito.TipoCredito c WHERE c.CodigoTipoCredito=k.TipoCredito)))
  THROW 57800,'Falta un tipo de producto o de crédito.',1;
 INSERT Contabilidad.ClaseCuentaProducto (IdTipoProducto,IdTipoCredito,CodigoRol,Situacion,Condicion,Tramo,CuentaBase,Nivel,Obligatorio,SoloConTasa,Orden)
 SELECT t.IdTipoProducto,c.IdTipoCredito,k.Rol,k.Situacion,k.Condicion,k.Tramo,k.Base,k.Nivel,k.Obligatorio,k.SoloConTasa,k.Orden
 FROM @clases k JOIN ProductosFinancieros.TipoProducto t ON t.Codigo=k.Tipo
 LEFT JOIN Credito.TipoCredito c ON c.CodigoTipoCredito=k.TipoCredito;

 /* 4. Asignaciones sembradas: los roles de nivel tipo a su cuenta base; capital por producto. */
 INSERT Contabilidad.CuentaProducto (IdClase,IdCuentaContable,VigenciaDesde)
 SELECT k.IdClase,c.IdCuentaContable,'20260101'
 FROM Contabilidad.ClaseCuentaProducto k JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=k.CuentaBase
 WHERE k.Nivel='TIPO';
 DECLARE @capital TABLE (Producto varchar(10), SubProducto varchar(15), Cuenta varchar(30));
 INSERT @capital VALUES ('AHO001',NULL,'21013505'),('AHO002',NULL,'21013515'),('AHO003',NULL,'21013520'),
  ('AHO004',NULL,'21013525'),('COR001',NULL,'21011005'),(NULL,'AHO001-PJ','21013510');
 INSERT Contabilidad.CuentaProducto (IdClase,IdProducto,IdSubProducto,IdCuentaContable,VigenciaDesde)
 -- La excepción por subproducto lleva solo IdSubProducto.
 SELECT k.IdClase,CASE WHEN x.SubProducto IS NULL THEN p.IdProducto END,s.IdSubProducto,c.IdCuentaContable,'20260101'
 FROM @capital x
 LEFT JOIN ProductosFinancieros.SubProducto s ON s.CodigoSubProducto=x.SubProducto
 JOIN ProductosFinancieros.Producto p ON p.IdProducto=COALESCE(s.IdProducto,(SELECT IdProducto FROM ProductosFinancieros.Producto WHERE CodigoProducto=x.Producto))
 JOIN Contabilidad.ClaseCuentaProducto k ON k.IdTipoProducto=p.IdTipoProducto AND k.CodigoRol='CAPITAL'
 JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=x.Cuenta;
 IF (SELECT COUNT(*) FROM Contabilidad.CuentaProducto v JOIN Contabilidad.ClaseCuentaProducto k ON k.IdClase=v.IdClase WHERE k.CodigoRol='CAPITAL' AND k.Nivel='PRODUCTO')<>6
  THROW 57800,'No se sembró el capital de todos los productos de depósito.',1;

 /* 5. Seguros e impuestos con su cuenta por pagar (D-16, H-5). */
 ALTER TABLE Credito.Seguro ADD IdCuentaContable int NULL CONSTRAINT FK_Seguro_Cuenta REFERENCES Contabilidad.CuentasContables(IdCuentaContable);
 ALTER TABLE Credito.Impuesto ADD IdCuentaContable int NULL CONSTRAINT FK_Impuesto_Cuenta REFERENCES Contabilidad.CuentasContables(IdCuentaContable);
 EXEC sys.sp_executesql N'
 UPDATE Credito.Seguro SET IdCuentaContable=(SELECT IdCuentaContable FROM Contabilidad.CuentasContables WHERE CodigoCuenta=''25909005'') WHERE CodigoSeguro=''DESGRAV'';
 UPDATE Credito.Impuesto SET IdCuentaContable=(SELECT IdCuentaContable FROM Contabilidad.CuentasContables WHERE CodigoCuenta=''25059005'') WHERE CodigoImpuesto=''SOLCA'';';

 /* 6. Categoría de servicio y cuenta de ingreso de las comisiones (H-17, D-14, D-15). */
 CREATE TABLE Transacciones.CategoriaServicio (
  Codigo varchar(16) NOT NULL CONSTRAINT PK_CategoriaServicio PRIMARY KEY,
  Nombre nvarchar(80) NOT NULL,
  IdCuentaContable int NULL CONSTRAINT FK_CategoriaServicio_Cuenta REFERENCES Contabilidad.CuentasContables(IdCuentaContable),
  PermiteCobro bit NOT NULL
 );
 INSERT Transacciones.CategoriaServicio (Codigo,Nombre,IdCuentaContable,PermiteCobro)
 SELECT v.Codigo,v.Nombre,c.IdCuentaContable,v.PermiteCobro
 FROM (VALUES ('BASICO',N'Servicio financiero básico (gratuito)',NULL,0),
              ('CARGO_MAXIMO',N'Servicio con cargo máximo','549005',1),
              ('DIFERENCIADO',N'Servicio con cargo diferenciado','549010',1),
              ('ENTRE_ENTIDADES',N'Comisión pagada por otra entidad o red','5290',1)) v(Codigo,Nombre,Cuenta,PermiteCobro)
 LEFT JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=v.Cuenta;
 IF EXISTS(SELECT 1 FROM Transacciones.CategoriaServicio WHERE PermiteCobro=1 AND IdCuentaContable IS NULL)
  THROW 57800,'Falta una cuenta de ingreso por servicios del CUC.',1;
 ALTER TABLE Transacciones.Comisiones ADD
  Categoria varchar(16) NULL CONSTRAINT FK_Comisiones_Categoria REFERENCES Transacciones.CategoriaServicio(Codigo),
  ValorMaximo decimal(18,4) NULL CONSTRAINT CK_Comisiones_ValorMaximo CHECK (ValorMaximo IS NULL OR ValorMaximo >= 0);
 EXEC sys.sp_executesql N'
 UPDATE Transacciones.Comisiones SET Categoria=''CARGO_MAXIMO'', ValorMaximo=0.45 WHERE CodigoComision=''RET-ATM'';
 UPDATE Transacciones.Comisiones SET Categoria=''CARGO_MAXIMO'', ValorMaximo=0.36 WHERE CodigoComision=''TRF-WEB'';
 -- Reposición de tarjeta de débito: servicio básico. No se reescribe la tarifa (eso es del flujo
 -- de aprobación de tarifas): la comisión se desactiva para que deje de cobrarse.
 UPDATE Transacciones.Comisiones SET Categoria=''BASICO'', Estado=''I'' WHERE CodigoComision=''REP-TDB'';
 UPDATE Transacciones.Comisiones SET Categoria=''DIFERENCIADO'' WHERE Categoria IS NULL;';
 EXEC sys.sp_executesql N'ALTER TABLE Transacciones.Comisiones ALTER COLUMN Categoria varchar(16) NOT NULL;';

 EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER Transacciones.trg_Comisiones_Categoria ON Transacciones.Comisiones
AFTER INSERT, UPDATE AS
BEGIN
 SET NOCOUNT ON;
 /* La cuenta de ingreso sale de la categoría del servicio (una sola fuente). */
 UPDATE c SET IdCuentaContableIngreso=k.IdCuentaContable
 FROM Transacciones.Comisiones c JOIN inserted i ON i.IdComision=c.IdComision
 JOIN Transacciones.CategoriaServicio k ON k.Codigo=c.Categoria
 WHERE ISNULL(c.IdCuentaContableIngreso,0)<>ISNULL(k.IdCuentaContable,0);
 IF EXISTS(SELECT 1 FROM inserted i JOIN Transacciones.CategoriaServicio k ON k.Codigo=i.Categoria
           JOIN Transacciones.vw_ComisionValorPresentacion v ON v.IdComision=i.IdComision
           WHERE i.Estado=''A'' AND ((k.PermiteCobro=0 AND v.Valor<>0)
              OR (i.TipoCalculo=''Fijo'' AND i.ValorMaximo IS NOT NULL AND v.Valor>i.ValorMaximo)))
  THROW 57283,N''COMISION_FUERA_DE_NORMA: un servicio básico no se cobra y un cargo no supera su máximo.'',1;
END;';
 EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER Transacciones.trg_ComisionValor_Norma ON Transacciones.ComisionValor
AFTER INSERT, UPDATE AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM inserted v JOIN Transacciones.Comisiones c ON c.IdComision=v.IdComision
           JOIN Transacciones.CategoriaServicio k ON k.Codigo=c.Categoria
           WHERE c.Estado=''A'' AND ((k.PermiteCobro=0 AND v.Valor<>0)
              OR (c.TipoCalculo=''Fijo'' AND c.ValorMaximo IS NOT NULL AND v.Valor>c.ValorMaximo)))
  THROW 57283,N''COMISION_FUERA_DE_NORMA: un servicio básico no se cobra y un cargo no supera su máximo.'',1;
END;';
 -- Aplica la cuenta a las filas existentes (el disparador corre en adelante).
 EXEC sys.sp_executesql N'
 UPDATE c SET IdCuentaContableIngreso=k.IdCuentaContable FROM Transacciones.Comisiones c JOIN Transacciones.CategoriaServicio k ON k.Codigo=c.Categoria;';

 /* 7. Vínculos: los seguros son del crédito (COMF art. 250) y el crédito no cobra comisiones
       (Res. 165-2015-F art. 12). Se corrigen los datos y se impide repetirlo (D-16, D-19). */
 EXEC sys.sp_executesql N'
 UPDATE v SET Estado=''I'' FROM ProductosFinancieros.ProductoSeguro v
 LEFT JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto=v.IdSubProducto
 JOIN ProductosFinancieros.Producto p ON p.IdProducto=COALESCE(v.IdProducto,s.IdProducto)
 JOIN ProductosFinancieros.TipoProducto t ON t.IdTipoProducto=p.IdTipoProducto
 WHERE v.Estado=''A'' AND t.Codigo<>''CREDITO'' AND NOT (t.Codigo=''TARJETA'' AND ISNULL(s.CodigoSubProducto,'''') LIKE ''TCR%'');
 UPDATE v SET Estado=''I'' FROM ProductosFinancieros.ProductoComision v
 LEFT JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto=v.IdSubProducto
 JOIN ProductosFinancieros.Producto p ON p.IdProducto=COALESCE(v.IdProducto,s.IdProducto)
 JOIN ProductosFinancieros.TipoProducto t ON t.IdTipoProducto=p.IdTipoProducto
 WHERE v.Estado=''A'' AND t.Codigo=''CREDITO'';';
 EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER ProductosFinancieros.trg_ProductoSeguro_SoloCredito ON ProductosFinancieros.ProductoSeguro
AFTER INSERT, UPDATE AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM inserted v
           LEFT JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto=v.IdSubProducto
           JOIN ProductosFinancieros.Producto p ON p.IdProducto=COALESCE(v.IdProducto,s.IdProducto)
           JOIN ProductosFinancieros.TipoProducto t ON t.IdTipoProducto=p.IdTipoProducto
           WHERE v.Estado=''A'' AND t.Codigo<>''CREDITO'' AND NOT (t.Codigo=''TARJETA'' AND ISNULL(s.CodigoSubProducto,'''') LIKE ''TCR%''))
  THROW 57284,N''SEGURO_SOLO_CREDITO: los seguros se exigen en operaciones de crédito.'',1;
END;';
 EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER ProductosFinancieros.trg_ProductoComision_NoCredito ON ProductosFinancieros.ProductoComision
AFTER INSERT, UPDATE AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM inserted v
           LEFT JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto=v.IdSubProducto
           JOIN ProductosFinancieros.Producto p ON p.IdProducto=COALESCE(v.IdProducto,s.IdProducto)
           JOIN ProductosFinancieros.TipoProducto t ON t.IdTipoProducto=p.IdTipoProducto
           WHERE v.Estado=''A'' AND t.Codigo=''CREDITO'')
  THROW 57285,N''COMISION_NO_APLICA_CREDITO: se prohíbe cobrar comisiones por operaciones de crédito.'',1;
END;';
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;

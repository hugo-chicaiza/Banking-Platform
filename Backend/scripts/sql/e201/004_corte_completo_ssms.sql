/* E201 CORTE COMPLETO SSMS. Instalar despues de 001_solo_estructura.sql.
No crea hijas ni cambia imputabilidad durante la instalacion.
El corte real solo se ejecuta por E201.usp_EjecutarCorte y todo se confirma junto.
Incluye autorizacion TEMPORAL por dos identidades SQL reales y roles especificos.
E0-08 no esta instalado: este registro NO es la cola E0-08.
El DBA debe verificar/vincular usuarios y permisos antes de preparar/aprobar.
Ver SSMS_CORTE.md para contrato y llamadas. Azure no fue modificado por el agente.
*/
/* E2-01. CONTRATO BD para el manejador E0-08; NO crea una aprobacion real.
   Ejecutar despues de 001, en ventana de mantenimiento. Sin miembros de roles
   por defecto: no habilita a un usuario final para fabricar autorizaciones.
   El adaptador confiable debe validar permisos, agencia, contador distinto,
   hash/version/estado en SeguridadDB y copiar el recibo y su manifiesto aqui.
   Sin ese adaptador NO ejecutar la reclasificacion en Azure.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;
IF DB_NAME()<>N'CooperativaDB' AND DB_NAME() NOT LIKE N'CooperativaDB_E201_Lab[_]%'
 THROW 56300,N'Base fuera del alcance E201.',1;
IF @@TRANCOUNT<>0 THROW 56300,N'Instalar sin transaccion previa.',1;
BEGIN TRY
BEGIN TRANSACTION;
IF SCHEMA_ID('E201') IS NULL EXEC('CREATE SCHEMA E201 AUTHORIZATION dbo');
IF DATABASE_PRINCIPAL_ID('E201_AdaptadorAprobacion') IS NULL CREATE ROLE E201_AdaptadorAprobacion;
IF DATABASE_PRINCIPAL_ID('E201_Ejecutor') IS NULL CREATE ROLE E201_Ejecutor;
IF EXISTS(SELECT 1 FROM Contabilidad.TiposAsiento WHERE Codigo='MANUAL_RECLASIFICACION'
 AND (EsManual<>1 OR Estado<>'A'))
 THROW 56309,N'Tipo MANUAL_RECLASIFICACION existente incompatible.',1;
IF NOT EXISTS(SELECT 1 FROM Contabilidad.TiposAsiento WHERE Codigo='MANUAL_RECLASIFICACION')
 INSERT Contabilidad.TiposAsiento(Codigo,Nombre,Descripcion,EsManual,Estado)
 VALUES('MANUAL_RECLASIFICACION','Reclasificacion aprobada','E201: manifiesto autorizado por segunda persona',1,'A');


/* Corte congelado: una fila por custodio/subproducto, importes NO constantes.
   Ahorro debe clasificarse por IdSubProducto confirmado por E3-01. No inferir
   persona natural/juridica solo desde TipoCliente ni usar saldo disponible.
   Fuente/Evidencia identifica consulta, corte y archivo revisable. */
IF OBJECT_ID('E201.ControlCorte') IS NULL
CREATE TABLE E201.ControlCorte(
 IdCorte uniqueidentifier NOT NULL,
 CodigoAuxiliar varchar(8) NOT NULL,
 IdCustodio varchar(60) NOT NULL,
 FechaCorte datetime2 NOT NULL,
 Monto decimal(18,2) NOT NULL CHECK(Monto>=0),
 Fuente varchar(250) NOT NULL,
 Evidencia varchar(500) NOT NULL,
 CONSTRAINT PK_E201_Control PRIMARY KEY(IdCorte,CodigoAuxiliar,IdCustodio),
 CONSTRAINT CK_E201_Control_Cuenta CHECK(CodigoAuxiliar IN
 ('11010505','11010510','11010515','21013505','21013510'))
);
IF OBJECT_ID('E201.Reclasificacion') IS NULL
CREATE TABLE E201.Reclasificacion(
 IdSolicitud bigint NOT NULL PRIMARY KEY,
 IdAsientoContable int NOT NULL UNIQUE
   REFERENCES Contabilidad.AsientoContable(IdAsientoContable),
 IdCorte uniqueidentifier NOT NULL,
 PreparadoPor int NOT NULL,
 AprobadoPor int NOT NULL,
 FechaAprobacion datetime2 NOT NULL,
 HashContenido binary(32) NOT NULL,
 Estado varchar(12) NOT NULL DEFAULT('AUTORIZADA'),
 FechaEjecucion datetime2 NULL,
 Alcance varchar(20) NOT NULL DEFAULT('EFECTIVO_AHORRO')
   CHECK(Alcance IN ('EFECTIVO','AHORRO','EFECTIVO_AHORRO')),
 CONSTRAINT CK_E201_DosPersonas CHECK(PreparadoPor<>AprobadoPor),
 CONSTRAINT CK_E201_Estado CHECK(Estado IN ('AUTORIZADA','EJECUTANDO','EJECUTADA'))
);
/* El adaptador solo registra esta evidencia despues de revisar la captura 003.
   EsEnsayo=1 no es aceptable en CooperativaDB. Hoy NO hay captura operativa
   conciliada disponible: no poblar esta tabla en Azure con las referencias. */
IF OBJECT_ID('E201.ValidacionCorte') IS NULL
CREATE TABLE E201.ValidacionCorte(
 IdCorte uniqueidentifier NOT NULL PRIMARY KEY,
 FechaCorte datetime2 NOT NULL,
 Libro210135 decimal(18,2) NOT NULL,
 LibroPN decimal(18,2) NOT NULL,
 LibroPJ decimal(18,2) NOT NULL,
 OperativoPN decimal(18,2) NOT NULL,
 OperativoPJ decimal(18,2) NOT NULL,
 LineasSinMapeo int NOT NULL,
 EsEnsayo bit NOT NULL,
 Evidencia varchar(500) NOT NULL,
 CONSTRAINT CK_E201_Conciliado CHECK(Libro210135=LibroPN+LibroPJ
 AND LibroPN=OperativoPN AND LibroPJ=OperativoPJ AND LineasSinMapeo=0)
);
IF OBJECT_ID('E201.LineaReclasificacion') IS NULL
CREATE TABLE E201.LineaReclasificacion(
 IdSolicitud bigint NOT NULL REFERENCES E201.Reclasificacion(IdSolicitud),
 Orden int NOT NULL,
 IdCuentaContable int NOT NULL REFERENCES Contabilidad.CuentasContables(IdCuentaContable),
 TipoMovimiento varchar(30) NOT NULL CHECK(TipoMovimiento IN ('DEBITO','CREDITO')),
 Monto decimal(18,2) NOT NULL CHECK(Monto>0),
 PRIMARY KEY(IdSolicitud,Orden),
 UNIQUE(IdSolicitud,IdCuentaContable)
);
/* Solo el adaptador de confianza registra el recibo validado. No conceder estos
   roles a contadores, aplicaciones generales ni usuarios de SSMS. */
GRANT SELECT,INSERT ON E201.ControlCorte TO E201_AdaptadorAprobacion;
GRANT SELECT,INSERT ON E201.Reclasificacion TO E201_AdaptadorAprobacion;
GRANT SELECT,INSERT ON E201.LineaReclasificacion TO E201_AdaptadorAprobacion;
GRANT SELECT,INSERT ON E201.ValidacionCorte TO E201_AdaptadorAprobacion;

EXEC sys.sp_executesql N'
CREATE OR ALTER VIEW E201.vw_SaldoPropio AS
SELECT c.IdCuentaContable,c.CodigoCuenta,c.CodigoElemento,c.Naturaleza,
 CONVERT(decimal(18,2),COALESCE(SUM(CASE WHEN a.Estado IN (''CONTABILIZADO'',''REVERSADO'')
 THEN CASE WHEN (c.Naturaleza=''DEUDORA'' AND m.TipoMovimiento=''DEBITO'')
                 OR (c.Naturaleza=''ACREEDORA'' AND m.TipoMovimiento=''CREDITO'')
           THEN m.Monto ELSE -m.Monto END ELSE 0 END),0)) AS SaldoPropio
FROM Contabilidad.CuentasContables c
LEFT JOIN Contabilidad.MovimientosContables m ON m.IdCuentaContable=c.IdCuentaContable
LEFT JOIN Contabilidad.AsientoContable a ON a.IdAsientoContable=m.IdAsientoContable
GROUP BY c.IdCuentaContable,c.CodigoCuenta,c.CodigoElemento,c.Naturaleza;
';
EXEC sys.sp_executesql N'
/* Cada auxiliar representa una CLASE de custodios; no un mayor independiente
   por boveda/ATM. No repetir el saldo contable para cada IdCustodio. */
CREATE OR ALTER VIEW E201.vw_ConciliacionEfectivo AS
WITH control AS (
 SELECT IdCorte,CodigoAuxiliar,MIN(FechaCorte) AS FechaCorte,
 MAX(FechaCorte) AS UltimaFechaCorte,COUNT(*) AS Custodios,SUM(Monto) AS Fisico
 FROM E201.ControlCorte WHERE CodigoAuxiliar LIKE ''110105%''
 GROUP BY IdCorte,CodigoAuxiliar
)
SELECT x.IdCorte,x.FechaCorte,x.UltimaFechaCorte,x.CodigoAuxiliar,x.Custodios,
 CONVERT(decimal(18,2),COALESCE(SUM(CASE WHEN a.Estado IN (''CONTABILIZADO'',''REVERSADO'')
 AND m.FechaHora<=x.FechaCorte THEN CASE WHEN m.TipoMovimiento=''DEBITO'' THEN m.Monto ELSE -m.Monto END
 ELSE 0 END),0)) AS ContableAlCorte,
 x.Fisico,
 CONVERT(decimal(18,2),COALESCE(SUM(CASE WHEN a.Estado IN (''CONTABILIZADO'',''REVERSADO'')
 AND m.FechaHora<=x.FechaCorte THEN CASE WHEN m.TipoMovimiento=''DEBITO'' THEN m.Monto ELSE -m.Monto END
 ELSE 0 END),0)-x.Fisico) AS Diferencia
FROM control x
JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=x.CodigoAuxiliar
LEFT JOIN Contabilidad.MovimientosContables m ON m.IdCuentaContable=c.IdCuentaContable
LEFT JOIN Contabilidad.AsientoContable a ON a.IdAsientoContable=m.IdAsientoContable
GROUP BY x.IdCorte,x.FechaCorte,x.UltimaFechaCorte,x.CodigoAuxiliar,x.Custodios,x.Fisico;
';
EXEC sys.sp_executesql N'
/* Un permiso de sesion NO es aprobacion. La excepcion requiere recibo protegido,
   mismo asiento BORRADOR, estado EJECUTANDO y linea exacta del manifiesto. */
CREATE OR ALTER FUNCTION E201.fn_LineaAutorizada
(@Asiento int,@Cuenta int,@Lado varchar(30),@Monto decimal(18,2))
RETURNS bit
AS
BEGIN
 RETURN CASE WHEN EXISTS(
 SELECT 1 FROM E201.Reclasificacion r
 JOIN E201.LineaReclasificacion l ON l.IdSolicitud=r.IdSolicitud
 JOIN Contabilidad.AsientoContable a ON a.IdAsientoContable=r.IdAsientoContable
 WHERE r.IdAsientoContable=@Asiento AND r.Estado=''EJECUTANDO''
 AND a.Estado=''BORRADOR'' AND a.IdUsuarioCreacion=r.PreparadoPor
 AND l.IdCuentaContable=@Cuenta AND l.TipoMovimiento=@Lado AND l.Monto=@Monto)
 THEN 1 ELSE 0 END;
END;
';

/* Conservar TODOS los demas controles del trigger vigente. Si cambia el texto
   esperado se detiene; cotejar definicion actual en SSMS antes de desplegar.
   No se deshabilita el trigger ni se renombra un trigger ajeno. */
DECLARE @sql nvarchar(max)=OBJECT_DEFINITION(OBJECT_ID('Contabilidad.trg_MovimientosContables_CuentaImputable'));
IF @sql IS NULL THROW 56310,N'Falta trigger CuentaImputable o permiso VIEW DEFINITION.',1;
IF @sql NOT LIKE '%E201.fn_LineaAutorizada%'
BEGIN
 IF @sql NOT LIKE '%WHERE c.EsImputable = 0 OR c.Estado = 0%'
  THROW 56310,N'Trigger distinto del revisado: no se modifica automaticamente.',1;
 SET @sql=REPLACE(@sql,'WHERE c.EsImputable = 0 OR c.Estado = 0',
 'WHERE c.Estado = 0 OR (c.EsImputable = 0 AND E201.fn_LineaAutorizada(i.IdAsientoContable,i.IdCuentaContable,i.TipoMovimiento,i.Monto)=0)');
 SET @sql=STUFF(@sql,1,CHARINDEX('TRIGGER',UPPER(@sql))-1,'ALTER ');
 EXEC sys.sp_executesql @sql;
END;

EXEC sys.sp_executesql N'
CREATE OR ALTER TRIGGER Contabilidad.trg_MovimientosContables_NivelE201
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
END;
';
EXEC sys.sp_executesql N'
CREATE OR ALTER PROCEDURE E201.usp_EjecutarReclasificacion @IdSolicitud bigint
AS
BEGIN
 SET NOCOUNT ON;
 SET XACT_ABORT ON;
 /* La transaccion externa del corte conserva altas, flags y asiento atomicos. */
 BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @Asiento int,@Corte uniqueidentifier,@Hash binary(32),@Estado varchar(12),@Fecha datetime2,@Alcance varchar(20);
 SELECT @Asiento=IdAsientoContable,@Corte=IdCorte,@Hash=HashContenido,@Estado=Estado,@Alcance=Alcance
 FROM E201.Reclasificacion WITH(UPDLOCK,HOLDLOCK) WHERE IdSolicitud=@IdSolicitud;
 IF @Estado IS NULL THROW 56314,N''No existe recibo de aprobacion.'',1;
 IF @Estado=''EJECUTADA'' BEGIN COMMIT; SELECT @Asiento AS IdAsientoContable,''YA_EJECUTADA'' AS Resultado; RETURN; END;
 IF @Estado<>''AUTORIZADA'' THROW 56314,N''Recibo no ejecutable.'',1;
 SELECT @Fecha=MIN(FechaCorte) FROM E201.ControlCorte WITH(UPDLOCK,HOLDLOCK) WHERE IdCorte=@Corte;
 IF @Fecha IS NULL OR EXISTS(SELECT 1 FROM E201.ControlCorte WHERE IdCorte=@Corte AND FechaCorte<>@Fecha)
  THROW 56315,N''Controles de cortes distintos o ausentes.'',1;
 IF @Alcance IN (''AHORRO'',''EFECTIVO_AHORRO'') AND NOT EXISTS(SELECT 1 FROM E201.ValidacionCorte v WITH(UPDLOCK,HOLDLOCK)
 WHERE v.IdCorte=@Corte AND v.FechaCorte=@Fecha AND (v.EsEnsayo=0 OR DB_NAME() LIKE N''CooperativaDB_E201_Lab[_]%'')
 AND v.LibroPN=(SELECT SUM(Monto) FROM E201.ControlCorte WHERE IdCorte=@Corte AND CodigoAuxiliar=''21013505'')
 AND v.LibroPJ=(SELECT SUM(Monto) FROM E201.ControlCorte WHERE IdCorte=@Corte AND CodigoAuxiliar=''21013510''))
  THROW 56323,N''Ahorro bloqueado: falta evidencia conciliada del mismo corte; referencias no autorizan ejecucion.'',1;
 IF NOT EXISTS(SELECT 1 FROM Contabilidad.AsientoContable a WITH(UPDLOCK,HOLDLOCK)
 JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento=a.IdTipoAsiento
 JOIN E201.Reclasificacion r ON r.IdAsientoContable=a.IdAsientoContable
 WHERE r.IdSolicitud=@IdSolicitud AND a.Estado=''BORRADOR''
 AND a.IdUsuarioCreacion=r.PreparadoPor AND a.FechaAsiento=CONVERT(date,@Fecha)
 AND t.Codigo=''MANUAL_RECLASIFICACION'' AND t.EsManual=1 AND t.Estado=''A'')
  THROW 56316,N''Asiento distinto del autorizado o tipo no habilitado.'',1;
 IF EXISTS(SELECT 1 FROM Contabilidad.MovimientosContables WITH(UPDLOCK,HOLDLOCK) WHERE IdAsientoContable=@Asiento)
  THROW 56316,N''El borrador ya tiene movimientos.'',1;
 /* Bloqueo de escrituras contables durante revalidacion y consumo. */
 DECLARE @n bigint;
 SELECT @n=COUNT_BIG(*) FROM Contabilidad.MovimientosContables WITH(TABLOCKX,HOLDLOCK);
 SELECT @n=COUNT_BIG(*) FROM Contabilidad.CuentasContables WITH(TABLOCKX,HOLDLOCK);
 DECLARE @Contenido nvarchar(max)=(SELECT @IdSolicitud AS Solicitud,@Asiento AS Asiento,@Corte AS Corte,
 JSON_QUERY((SELECT a.NumeroAsiento,a.FechaAsiento,a.FechaSistema,a.IdTipoAsiento,a.Origen,a.Concepto,
 a.IdUsuarioCreacion,a.IdAgencia,a.IdConceptoContable,a.IdFechaContable,r.PreparadoPor,r.AprobadoPor,r.FechaAprobacion,r.Alcance
 FROM Contabilidad.AsientoContable a JOIN E201.Reclasificacion r ON r.IdAsientoContable=a.IdAsientoContable
 WHERE r.IdSolicitud=@IdSolicitud FOR JSON PATH,WITHOUT_ARRAY_WRAPPER)) AS Cabecera,
 JSON_QUERY((SELECT Orden,IdCuentaContable,TipoMovimiento,Monto FROM E201.LineaReclasificacion WITH(HOLDLOCK)
 WHERE IdSolicitud=@IdSolicitud ORDER BY Orden FOR JSON PATH)) AS Lineas,
 JSON_QUERY((SELECT CodigoAuxiliar,IdCustodio,FechaCorte,Monto,Fuente,Evidencia FROM E201.ControlCorte
 WHERE IdCorte=@Corte ORDER BY CodigoAuxiliar,IdCustodio FOR JSON PATH)) AS Controles,
 JSON_QUERY((SELECT FechaCorte,Libro210135,LibroPN,LibroPJ,OperativoPN,OperativoPJ,LineasSinMapeo,EsEnsayo,Evidencia
 FROM E201.ValidacionCorte WHERE IdCorte=@Corte FOR JSON PATH,WITHOUT_ARRAY_WRAPPER)) AS Conciliacion
 FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
 IF HASHBYTES(''SHA2_256'',@Contenido)<>@Hash THROW 56317,N''Contenido distinto del aprobado.'',1;
 /* Solo cinco destinos confirmados. No permite descargar cartera ni otras cuentas. */
 IF EXISTS(SELECT 1 FROM E201.LineaReclasificacion l JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=l.IdCuentaContable
 WHERE l.IdSolicitud=@IdSolicitud AND (c.CodigoCuenta NOT IN
 (''110105'',''210135'',''11010505'',''11010510'',''11010515'',''21013505'',''21013510'') OR c.Estado<>1
 OR (LEN(c.CodigoCuenta)=8 AND (c.EsImputable<>1 OR c.SoloAutomatica<>1))))
  THROW 56318,N''Destino no confirmado o inactivo.'',1;
 IF (SELECT COUNT(DISTINCT CodigoAuxiliar) FROM E201.ControlCorte WHERE IdCorte=@Corte)<>
 CASE @Alcance WHEN ''EFECTIVO'' THEN 3 WHEN ''AHORRO'' THEN 2 ELSE 5 END
 OR EXISTS(SELECT 1 FROM E201.ControlCorte WHERE IdCorte=@Corte AND
 ((@Alcance=''EFECTIVO'' AND CodigoAuxiliar LIKE ''210135%'') OR (@Alcance=''AHORRO'' AND CodigoAuxiliar LIKE ''110105%'')))
  THROW 56319,N''Controles incompletos o fuera del alcance; incluir ceros documentados.'',1;
 DECLARE @Esperadas TABLE(IdCuentaContable int PRIMARY KEY,TipoMovimiento varchar(30),Monto decimal(18,2));
 INSERT INTO @Esperadas
 SELECT c.IdCuentaContable,CASE WHEN c.Naturaleza=''DEUDORA'' THEN ''DEBITO'' ELSE ''CREDITO'' END,SUM(k.Monto)
 FROM E201.ControlCorte k JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=k.CodigoAuxiliar
 WHERE k.IdCorte=@Corte GROUP BY c.IdCuentaContable,c.Naturaleza HAVING SUM(k.Monto)>0;
 INSERT INTO @Esperadas
 SELECT p.IdCuentaContable,CASE WHEN p.Naturaleza=''DEUDORA'' THEN ''CREDITO'' ELSE ''DEBITO'' END,SUM(k.Monto)
 FROM E201.ControlCorte k JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=k.CodigoAuxiliar
 JOIN Contabilidad.CuentasContables p ON p.IdCuentaContable=c.IdCuentaSuperior
 WHERE k.IdCorte=@Corte GROUP BY p.IdCuentaContable,p.Naturaleza HAVING SUM(k.Monto)>0;
 IF EXISTS(SELECT IdCuentaContable,TipoMovimiento,Monto FROM @Esperadas EXCEPT
 SELECT IdCuentaContable,TipoMovimiento,Monto FROM E201.LineaReclasificacion WHERE IdSolicitud=@IdSolicitud)
 OR EXISTS(SELECT IdCuentaContable,TipoMovimiento,Monto FROM E201.LineaReclasificacion WHERE IdSolicitud=@IdSolicitud EXCEPT
 SELECT IdCuentaContable,TipoMovimiento,Monto FROM @Esperadas)
  THROW 56320,N''Manifiesto no coincide con el corte completo.'',1;
 IF EXISTS(SELECT 1 FROM E201.vw_SaldoPropio s JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=s.IdCuentaContable
 WHERE c.CodigoCuenta IN (''110105'',''210135'')
 AND EXISTS(SELECT 1 FROM E201.ControlCorte k JOIN Contabilidad.CuentasContables h ON h.CodigoCuenta=k.CodigoAuxiliar
 WHERE k.IdCorte=@Corte AND h.IdCuentaSuperior=c.IdCuentaContable) AND s.SaldoPropio<>
 COALESCE((SELECT SUM(k.Monto) FROM E201.ControlCorte k JOIN Contabilidad.CuentasContables h ON h.CodigoCuenta=k.CodigoAuxiliar
 WHERE k.IdCorte=@Corte AND h.IdCuentaSuperior=c.IdCuentaContable),0))
 OR EXISTS(SELECT 1 FROM E201.vw_SaldoPropio WHERE CodigoCuenta IN
 (''11010505'',''11010510'',''11010515'',''21013505'',''21013510'') AND SaldoPropio<>0
 AND CodigoCuenta IN (SELECT CodigoAuxiliar FROM E201.ControlCorte WHERE IdCorte=@Corte))
  THROW 56321,N''Saldos propios cambiaron o no concilian con el corte.'',1;
 DECLARE @Antes TABLE(Elemento char(1),Total decimal(38,2));
 INSERT INTO @Antes SELECT CodigoElemento,SUM(SaldoPropio) FROM E201.vw_SaldoPropio GROUP BY CodigoElemento;
 UPDATE E201.Reclasificacion SET Estado=''EJECUTANDO'' WHERE IdSolicitud=@IdSolicitud;
 INSERT INTO Contabilidad.MovimientosContables
 (IdCuentaContable,IdTransaccion,IdAgencia,TipoMovimiento,Monto,FechaHora,IdAsientoContable)
 SELECT l.IdCuentaContable,NULL,a.IdAgencia,l.TipoMovimiento,l.Monto,@Fecha,@Asiento
 FROM E201.LineaReclasificacion l JOIN Contabilidad.AsientoContable a ON a.IdAsientoContable=@Asiento
 WHERE l.IdSolicitud=@IdSolicitud;
 EXEC Contabilidad.usp_ContabilizarAsiento @IdAsientoContable=@Asiento;
 /* Saldo es acumulado de subarbol en el esquema observado. Aplicar delta a
    cuenta y ascendientes; padre conserva subtotal pero su saldo PROPIO queda 0.
    Si el sistema incorpora otro actualizador de saldos, revisar este bloque
    para evitar doble aplicacion. No se toca ninguna linea historica. */
 ;WITH delta AS (
 SELECT c.IdCuentaContable,c.IdCuentaSuperior,
 CONVERT(decimal(18,2),CASE WHEN (c.Naturaleza=''DEUDORA'' AND l.TipoMovimiento=''DEBITO'')
 OR (c.Naturaleza=''ACREEDORA'' AND l.TipoMovimiento=''CREDITO'') THEN l.Monto ELSE -l.Monto END) AS Monto
 FROM E201.LineaReclasificacion l JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=l.IdCuentaContable
 WHERE l.IdSolicitud=@IdSolicitud
 UNION ALL
 SELECT p.IdCuentaContable,p.IdCuentaSuperior,d.Monto FROM delta d
 JOIN Contabilidad.CuentasContables p ON p.IdCuentaContable=d.IdCuentaSuperior
 ), totales AS (SELECT IdCuentaContable,SUM(Monto) AS Monto FROM delta GROUP BY IdCuentaContable)
 UPDATE c SET Saldo=c.Saldo+t.Monto FROM Contabilidad.CuentasContables c JOIN totales t ON t.IdCuentaContable=c.IdCuentaContable
 OPTION(MAXRECURSION 100);
 IF EXISTS(SELECT Elemento,Total FROM @Antes EXCEPT SELECT CodigoElemento,SUM(SaldoPropio) FROM E201.vw_SaldoPropio GROUP BY CodigoElemento)
  THROW 56322,N''Cambio de total por elemento.'',1;
 IF EXISTS(SELECT 1 FROM E201.vw_SaldoPropio s WHERE CodigoCuenta IN (''110105'',''210135'') AND SaldoPropio<>0
 AND EXISTS(SELECT 1 FROM E201.ControlCorte k JOIN Contabilidad.CuentasContables h ON h.CodigoCuenta=k.CodigoAuxiliar
 WHERE k.IdCorte=@Corte AND h.IdCuentaSuperior=s.IdCuentaContable))
  THROW 56322,N''Origen con saldo propio residual.'',1;
 UPDATE E201.Reclasificacion SET Estado=''EJECUTADA'',FechaEjecucion=SYSUTCDATETIME() WHERE IdSolicitud=@IdSolicitud;
 COMMIT;
 SELECT @Asiento AS IdAsientoContable,''EJECUTADA'' AS Resultado;
 END TRY
 BEGIN CATCH
  IF XACT_STATE()<>0 ROLLBACK;
  THROW;
 END CATCH;
END;
';

GRANT EXECUTE ON E201.usp_EjecutarReclasificacion TO E201_Ejecutor;


COMMIT;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK;
 THROW;
END CATCH;

REVOKE EXECUTE ON E201.usp_EjecutarReclasificacion FROM E201_Ejecutor;
REVOKE INSERT ON E201.ControlCorte FROM E201_AdaptadorAprobacion;
REVOKE INSERT ON E201.Reclasificacion FROM E201_AdaptadorAprobacion;
REVOKE INSERT ON E201.LineaReclasificacion FROM E201_AdaptadorAprobacion;
REVOKE INSERT ON E201.ValidacionCorte FROM E201_AdaptadorAprobacion;

EXEC sys.sp_executesql N'CREATE OR ALTER PROCEDURE E201.usp_AltaAuxiliaresEnCorte AS
BEGIN
 IF @@TRANCOUNT=0 THROW 56400,N''Alta solo dentro del corte atomico.'',1;

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID(''Contabilidad.CuentasContables'')
 AND ((name IN (''SoloAutomatica'',''EsCatalogoRegulador'') AND (TYPE_NAME(user_type_id)<>''bit'' OR is_nullable=1))
 OR (name=''Nivel'' AND is_computed<>1)))
 THROW 56302,N''Columnas E201 existentes incompatibles.'',1;
DECLARE @Altas TABLE(Codigo varchar(8) PRIMARY KEY,Padre varchar(6),Nombre varchar(150));
INSERT INTO @Altas VALUES
 (''11010505'',''110105'',''Efectivo en bovedas''),
 (''11010510'',''110105'',''Efectivo en ventanillas''),
 (''11010515'',''110105'',''Efectivo en cajeros automaticos''),
 (''21013505'',''210135'',''Ahorro a la vista persona natural''),
 (''21013510'',''210135'',''Ahorro a la vista persona juridica'');
IF (SELECT COUNT(*) FROM Contabilidad.CuentasContables WITH(UPDLOCK,HOLDLOCK)
 WHERE CodigoCuenta IN (''110105'',''210135'') AND Estado=1)<>2
 THROW 56303,N''Faltan padres activos.'',1;
IF EXISTS (SELECT 1 FROM @Altas a JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=a.Codigo
 JOIN Contabilidad.CuentasContables p ON p.CodigoCuenta=a.Padre
 WHERE c.IdCuentaSuperior<>p.IdCuentaContable OR c.IdCuentaSuperior IS NULL
 OR c.Naturaleza<>p.Naturaleza OR c.EsCuentaValuacion<>p.EsCuentaValuacion
 OR c.Estado<>p.Estado OR c.EsImputable<>1 OR c.SoloAutomatica<>1 OR c.EsCatalogoRegulador<>0)
 THROW 56304,N''Auxiliar existente incompatible: no se reemplaza.'',1;
/* 51100: primero padre no imputable; historico y saldo se conservan.
   La salida de su saldo propio se permite SOLO por el manifiesto aprobado (002).
   No se marca todo el catalogo como no imputable a ciegas. */
UPDATE Contabilidad.CuentasContables SET EsImputable=0,SoloAutomatica=1
 WHERE CodigoCuenta IN (''110105'',''210135'');
UPDATE Contabilidad.CuentasContables SET EsCatalogoRegulador=1
 WHERE CodigoCuenta IN (''110105'',''210135'');
INSERT INTO Contabilidad.CuentasContables
 (CodigoCuenta,NombreCuenta,Naturaleza,IdCuentaSuperior,Saldo,Estado,FechaCreacion,
  EsImputable,EsCuentaValuacion,SoloAutomatica,EsCatalogoRegulador)
SELECT a.Codigo,a.Nombre,p.Naturaleza,p.IdCuentaContable,0,p.Estado,
 CONVERT(datetime2,SYSDATETIMEOFFSET() AT TIME ZONE ''SA Pacific Standard Time''),
 1,p.EsCuentaValuacion,1,0
FROM @Altas a JOIN Contabilidad.CuentasContables p ON p.CodigoCuenta=a.Padre
WHERE NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables c WITH(UPDLOCK,HOLDLOCK) WHERE c.CodigoCuenta=a.Codigo);
END;';

EXEC sys.sp_executesql N'CREATE OR ALTER PROCEDURE E201.usp_HashInterno @IdSolicitud bigint AS BEGIN
DECLARE @Asiento int,@Corte uniqueidentifier; SELECT @Asiento=IdAsientoContable,@Corte=IdCorte FROM E201.Reclasificacion WHERE IdSolicitud=@IdSolicitud;
 DECLARE @Contenido nvarchar(max)=(SELECT @IdSolicitud AS Solicitud,@Asiento AS Asiento,@Corte AS Corte,
 JSON_QUERY((SELECT a.NumeroAsiento,a.FechaAsiento,a.FechaSistema,a.IdTipoAsiento,a.Origen,a.Concepto,
 a.IdUsuarioCreacion,a.IdAgencia,a.IdConceptoContable,a.IdFechaContable,r.PreparadoPor,r.AprobadoPor,r.FechaAprobacion,r.Alcance
 FROM Contabilidad.AsientoContable a JOIN E201.Reclasificacion r ON r.IdAsientoContable=a.IdAsientoContable
 WHERE r.IdSolicitud=@IdSolicitud FOR JSON PATH,WITHOUT_ARRAY_WRAPPER)) AS Cabecera,
 JSON_QUERY((SELECT Orden,IdCuentaContable,TipoMovimiento,Monto FROM E201.LineaReclasificacion WITH(HOLDLOCK)
 WHERE IdSolicitud=@IdSolicitud ORDER BY Orden FOR JSON PATH)) AS Lineas,
 JSON_QUERY((SELECT CodigoAuxiliar,IdCustodio,FechaCorte,Monto,Fuente,Evidencia FROM E201.ControlCorte
 WHERE IdCorte=@Corte ORDER BY CodigoAuxiliar,IdCustodio FOR JSON PATH)) AS Controles,
 JSON_QUERY((SELECT FechaCorte,Libro210135,LibroPN,LibroPJ,OperativoPN,OperativoPJ,LineasSinMapeo,EsEnsayo,Evidencia
 FROM E201.ValidacionCorte WHERE IdCorte=@Corte FOR JSON PATH,WITHOUT_ARRAY_WRAPPER)) AS Conciliacion
 FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
 UPDATE E201.Reclasificacion SET HashContenido=HASHBYTES(''SHA2_256'',@Contenido) WHERE IdSolicitud=@IdSolicitud;
END;';

/* Fuente legible del bloque nuevo. El entregable SSMS completo es
   004_corte_completo_ssms.sql (incluye dependencias e instalacion).
   Autorizacion temporal real por identidades SQL separadas; NO es la cola E0-08.
*/
IF OBJECT_ID('E201.PlanCorte') IS NULL
CREATE TABLE E201.PlanCorte(
 IdPlan uniqueidentifier NOT NULL PRIMARY KEY,
 Contenido nvarchar(max) NOT NULL CHECK(ISJSON(Contenido)=1),
 HashPlan binary(32) NOT NULL,
 VersionObjetivo binary(32) NOT NULL,
 FechaPreparacion datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
 LoginPreparador nvarchar(128) NOT NULL,
 PrincipalPreparador varbinary(85) NOT NULL
);
IF OBJECT_ID('E201.ReciboReal') IS NULL
CREATE TABLE E201.ReciboReal(
 IdSolicitud bigint NOT NULL PRIMARY KEY,
 IdPlan uniqueidentifier NOT NULL UNIQUE REFERENCES E201.PlanCorte(IdPlan),
 PreparadoPor int NOT NULL,AprobadoPor int NOT NULL,
 FechaAprobacion datetime2 NOT NULL,
 HashPlan binary(32) NOT NULL,
 Estado varchar(12) NOT NULL CHECK(Estado IN ('AUTORIZADA','EJECUTADA')),
 IdAsientoContable int NULL REFERENCES Contabilidad.AsientoContable(IdAsientoContable),
 CHECK(PreparadoPor<>AprobadoPor)
);

EXEC sys.sp_executesql N'
CREATE OR ALTER PROCEDURE E201.usp_VersionObjetivo @Version binary(32) OUTPUT
AS
BEGIN
 DECLARE @j nvarchar(max)=(SELECT c.IdCuentaContable,c.CodigoCuenta,c.IdCuentaSuperior,
 c.Naturaleza,c.Estado,c.EsImputable,c.EsCuentaValuacion,c.SoloAutomatica,c.Saldo,
 c.FechaModificacion,s.SaldoPropio
 FROM Contabilidad.CuentasContables c JOIN E201.vw_SaldoPropio s ON s.IdCuentaContable=c.IdCuentaContable
 WHERE c.CodigoCuenta IN (''110105'',''210135'',''11010505'',''11010510'',''11010515'',''21013505'',''21013510'')
 ORDER BY c.CodigoCuenta FOR JSON PATH);
 SET @Version=HASHBYTES(''SHA2_256'',@j);
END;
';
EXEC sys.sp_executesql N'
CREATE OR ALTER PROCEDURE E201.usp_PrepararCorte
 @IdPlan uniqueidentifier,@Contenido nvarchar(max)
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 DECLARE @Usuario int;
 SELECT @Usuario=UsuarioID FROM E201.IdentidadCorte
 WHERE PrincipalSID=USER_SID() AND NombreLogin=ORIGINAL_LOGIN() AND Activo=1 AND AlcanceInstitucional=1;
 IF @Usuario IS NULL OR COALESCE(IS_ROLEMEMBER(''E201_PreparadorCorte''),0)<>1
  THROW 56410,N''Preparador sin identidad de contador y permiso SQL efectivo.'',1;
 IF ISJSON(@Contenido)<>1 THROW 56401,N''Plan JSON invalido.'',1;
 IF TRY_CONVERT(uniqueidentifier,JSON_VALUE(@Contenido,''$.IdPlan''))<>@IdPlan
 OR JSON_VALUE(@Contenido,''$.IdPlan'') IS NULL THROW 56401,N''IdPlan no coincide.'',1;
 IF TRY_CONVERT(int,JSON_VALUE(@Contenido,''$.PreparadoPor''))<>@Usuario
 OR JSON_VALUE(@Contenido,''$.PreparadoPor'') IS NULL
  THROW 56410,N''PreparadoPor no corresponde a la identidad SQL autenticada.'',1;
 IF COALESCE(JSON_VALUE(@Contenido,''$.Alcance''),'''')<>''EFECTIVO_AHORRO''
  THROW 56401,N''Este guion atomico requiere el corte completo de efectivo y ahorro.'',1;
 IF EXISTS(SELECT 1 FROM E201.PlanCorte WHERE IdPlan=@IdPlan)
  THROW 56401,N''Plan ya congelado. No se edita; preparar una solicitud nueva.'',1;
 DECLARE @v binary(32);
 EXEC E201.usp_VersionObjetivo @v OUTPUT;
 INSERT E201.PlanCorte(IdPlan,Contenido,HashPlan,VersionObjetivo,LoginPreparador,PrincipalPreparador)
 VALUES(@IdPlan,@Contenido,HASHBYTES(''SHA2_256'',@Contenido),@v,ORIGINAL_LOGIN(),USER_SID());
 SELECT IdPlan,Contenido,CONVERT(varchar(64),HashPlan,2) AS HashPlanSHA256_UTF16LE,
 CONVERT(varchar(64),VersionObjetivo,2) AS VersionObjetivo
 FROM E201.PlanCorte WHERE IdPlan=@IdPlan;
END;
';
EXEC sys.sp_executesql N'
/* Validador instalado por corte_aprobacion_ssms_fuente.sql, no un flag libre:
 E201.usp_ValidarAprobacionCorte
 @IdSolicitud bigint,@IdPlan uniqueidentifier,@HashPlan binary(32),
 @PreparadoPor int OUTPUT,@AprobadoPor int OUTPUT,@FechaAprobacion datetime2 OUTPUT.
 Lee AutorizacionSSMS inmutable, verifica contenido/hash/objetivo, identidades
 vinculadas vigentes, roles SQL especificos y alcance institucional; niega
 autoaprobacion y comparte login. Revalida tambien al ejecutar.
 No implementamos este contrato con parametros "Permiso=1" ni RolesWorkOS cacheados.
 Sin definicion real instalada se rechaza con 56402. */
CREATE OR ALTER PROCEDURE E201.usp_RegistrarAprobacionReal
 @IdSolicitud bigint,@IdPlan uniqueidentifier
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 IF OBJECT_ID(''E201.usp_ValidarAprobacionCorte'',''P'') IS NULL
  THROW 56402,N''Falta validador real del corte: no se emite recibo.'',1;
 BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @j nvarchar(max),@h binary(32),@p int,@a int,@f datetime2;
 SELECT @j=Contenido,@h=HashPlan FROM E201.PlanCorte WITH(UPDLOCK,HOLDLOCK) WHERE IdPlan=@IdPlan;
 IF @j IS NULL OR @h<>HASHBYTES(''SHA2_256'',@j) THROW 56403,N''Plan ausente o alterado.'',1;
 EXEC E201.usp_ValidarAprobacionCorte @IdSolicitud,@IdPlan,@h,@p OUTPUT,@a OUTPUT,@f OUTPUT;
 IF @p IS NULL OR @a IS NULL OR @p=@a OR @f IS NULL
 OR @p<>TRY_CONVERT(int,JSON_VALUE(@j,''$.PreparadoPor''))
  THROW 56404,N''Identidades de aprobacion invalidas o distintas del plan.'',1;
 INSERT E201.ReciboReal VALUES(@IdSolicitud,@IdPlan,@p,@a,@f,@h,''AUTORIZADA'',NULL);
 COMMIT;
 SELECT * FROM E201.ReciboReal WHERE IdSolicitud=@IdSolicitud;
 END TRY BEGIN CATCH IF XACT_STATE()<>0 ROLLBACK; THROW; END CATCH;
END;
';
EXEC sys.sp_executesql N'
CREATE OR ALTER PROCEDURE E201.usp_EjecutarCorte @IdSolicitud bigint
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 IF @@TRANCOUNT<>0 THROW 56405,N''Invocar sin transaccion previa.'',1;
 IF OBJECT_ID(''E201.usp_ValidarAprobacionCorte'',''P'') IS NULL
  THROW 56402,N''Falta validador real del corte: corte no habilitado.'',1;
 BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @plan uniqueidentifier,@j nvarchar(max),@h binary(32),@version binary(32),@actual binary(32),
 @p int,@a int,@f datetime2,@rp int,@ra int,@rf datetime2,@estado varchar(12),@asiento int,@corte uniqueidentifier,@fecha datetime2;
 SELECT @plan=IdPlan,@p=PreparadoPor,@a=AprobadoPor,@f=FechaAprobacion,@h=HashPlan,
 @estado=Estado,@asiento=IdAsientoContable FROM E201.ReciboReal WITH(UPDLOCK,HOLDLOCK) WHERE IdSolicitud=@IdSolicitud;
 IF @estado IS NULL THROW 56406,N''Recibo real no registrado.'',1;
 IF @estado=''EJECUTADA'' BEGIN COMMIT; SELECT @asiento AS IdAsientoContable,''YA_EJECUTADA'' AS Resultado; RETURN; END;
 SELECT @j=Contenido,@version=VersionObjetivo FROM E201.PlanCorte WITH(HOLDLOCK) WHERE IdPlan=@plan;
 IF @h<>HASHBYTES(''SHA2_256'',@j) THROW 56403,N''Contenido del plan alterado.'',1;
 EXEC E201.usp_ValidarAprobacionCorte @IdSolicitud,@plan,@h,@rp OUTPUT,@ra OUTPUT,@rf OUTPUT;
 IF @rp IS NULL OR @ra IS NULL OR @rf IS NULL OR @rp<>@p OR @ra<>@a OR @rf<>@f OR @rp=@ra
  THROW 56404,N''Recibo revocado o identidades distintas.'',1;
 DECLARE @n bigint;
 SELECT @n=COUNT_BIG(*) FROM Contabilidad.CuentasContables WITH(TABLOCKX,HOLDLOCK);
 SELECT @n=COUNT_BIG(*) FROM Contabilidad.MovimientosContables WITH(TABLOCKX,HOLDLOCK);
 EXEC E201.usp_VersionObjetivo @actual OUTPUT;
 IF @actual<>@version THROW 56407,N''Objetivo cambio desde la preparacion: solicitar nueva aprobacion.'',1;
 SELECT @corte=TRY_CONVERT(uniqueidentifier,JSON_VALUE(@j,''$.IdCorte'')),
 @fecha=TRY_CONVERT(datetime2,JSON_VALUE(@j,''$.FechaCorte''));
 IF @corte IS NULL OR @fecha IS NULL THROW 56401,N''Falta identificacion del corte.'',1;
 /* 51100: padre no imputable ANTES de insertar hijas; aun SIN COMMIT. */
 EXEC E201.usp_AltaAuxiliaresEnCorte;
 INSERT E201.ControlCorte(IdCorte,CodigoAuxiliar,IdCustodio,FechaCorte,Monto,Fuente,Evidencia)
 SELECT @corte,CodigoAuxiliar,IdCustodio,@fecha,Monto,Fuente,Evidencia
 FROM OPENJSON(@j,''$.Controles'') WITH(CodigoAuxiliar varchar(8),IdCustodio varchar(60),
 Monto decimal(18,2),Fuente varchar(250),Evidencia varchar(500));
 INSERT E201.ValidacionCorte
 SELECT @corte,@fecha,Libro210135,LibroPN,LibroPJ,OperativoPN,OperativoPJ,LineasSinMapeo,EsEnsayo,Evidencia
 FROM OPENJSON(@j,''$.ConciliacionAhorro'') WITH(Libro210135 decimal(18,2),LibroPN decimal(18,2),LibroPJ decimal(18,2),
 OperativoPN decimal(18,2),OperativoPJ decimal(18,2),LineasSinMapeo int,EsEnsayo bit,Evidencia varchar(500));
 INSERT Contabilidad.AsientoContable
 (NumeroAsiento,FechaAsiento,FechaSistema,IdTipoAsiento,Origen,Concepto,TotalDebito,TotalCredito,
 Estado,IdUsuarioCreacion,IdAgencia,IdFechaContable)
 SELECT JSON_VALUE(@j,''$.NumeroAsiento''),CONVERT(date,@fecha),@fecha,t.IdTipoAsiento,''AJUSTE'',
 ''E201 corte aprobado por segunda persona'',0,0,''BORRADOR'',@p,JSON_VALUE(@j,''$.IdAgencia''),
 TRY_CONVERT(int,JSON_VALUE(@j,''$.IdFechaContable''))
 FROM Contabilidad.TiposAsiento t WHERE t.Codigo=''MANUAL_RECLASIFICACION'';
 SET @asiento=CONVERT(int,SCOPE_IDENTITY());
 INSERT E201.Reclasificacion
 (IdSolicitud,IdAsientoContable,IdCorte,PreparadoPor,AprobadoPor,FechaAprobacion,HashContenido,Estado,Alcance)
 VALUES(@IdSolicitud,@asiento,@corte,@p,@a,@f,0x00,''AUTORIZADA'',JSON_VALUE(@j,''$.Alcance''));
 ;WITH destinos AS(
 SELECT c.IdCuentaContable,c.Naturaleza,c.IdCuentaSuperior,SUM(k.Monto) AS Monto
 FROM E201.ControlCorte k JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=k.CodigoAuxiliar
 WHERE k.IdCorte=@corte GROUP BY c.IdCuentaContable,c.Naturaleza,c.IdCuentaSuperior HAVING SUM(k.Monto)>0
 ),lineas AS(
 SELECT IdCuentaContable,CASE Naturaleza WHEN ''DEUDORA'' THEN ''DEBITO'' ELSE ''CREDITO'' END AS Lado,Monto FROM destinos
 UNION ALL SELECT p.IdCuentaContable,CASE p.Naturaleza WHEN ''DEUDORA'' THEN ''CREDITO'' ELSE ''DEBITO'' END,SUM(d.Monto)
 FROM destinos d JOIN Contabilidad.CuentasContables p ON p.IdCuentaContable=d.IdCuentaSuperior
 GROUP BY p.IdCuentaContable,p.Naturaleza)
 INSERT E201.LineaReclasificacion
 SELECT @IdSolicitud,CONVERT(int,ROW_NUMBER() OVER(ORDER BY IdCuentaContable)),IdCuentaContable,Lado,Monto FROM lineas;
 EXEC E201.usp_HashInterno @IdSolicitud;
 /* Motor interno anida su transaccion. Su COMMIT NO confirma esta transaccion.
    Cualquier fallo revierte hijas, flags, controles, asiento y consumo juntos. */
 EXEC E201.usp_EjecutarReclasificacion @IdSolicitud;
 UPDATE E201.ReciboReal SET Estado=''EJECUTADA'',IdAsientoContable=@asiento WHERE IdSolicitud=@IdSolicitud;
 COMMIT;
 SELECT @asiento AS IdAsientoContable,''CORTE_EJECUTADO'' AS Resultado;
 END TRY
 BEGIN CATCH IF XACT_STATE()<>0 ROLLBACK; THROW; END CATCH;
END;
';

GRANT EXECUTE ON E201.usp_PrepararCorte TO E201_AdaptadorAprobacion;
GRANT EXECUTE ON E201.usp_RegistrarAprobacionReal TO E201_AdaptadorAprobacion;
GRANT EXECUTE ON E201.usp_EjecutarCorte TO E201_Ejecutor;
/* Sin permisos DML de negocio ni EXEC al motor/hash/alta internos para los roles. */


/* Autorizacion temporal de un corte por DOS identidades SQL autenticadas.
   El DBA vincula identidades verificadas de contadores y asigna roles.
   No se autoconcede permisos, no consulta roles WorkOS cacheados, no simula E0-08. */
IF DATABASE_PRINCIPAL_ID('E201_PreparadorCorte') IS NULL CREATE ROLE E201_PreparadorCorte;
IF DATABASE_PRINCIPAL_ID('E201_AprobadorCorte') IS NULL CREATE ROLE E201_AprobadorCorte;
IF OBJECT_ID('E201.IdentidadCorte') IS NULL
CREATE TABLE E201.IdentidadCorte(
 PrincipalSID varbinary(85) NOT NULL PRIMARY KEY,
 NombreLogin nvarchar(128) NOT NULL,
 UsuarioID int NOT NULL UNIQUE,
 Activo bit NOT NULL,
 AlcanceInstitucional bit NOT NULL,
 EvidenciaVerificacion varchar(500) NOT NULL
);
IF OBJECT_ID('E201.AutorizacionSSMS') IS NULL
CREATE TABLE E201.AutorizacionSSMS(
 IdSolicitud bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
 IdPlan uniqueidentifier NOT NULL UNIQUE REFERENCES E201.PlanCorte(IdPlan),
 HashPlan binary(32) NOT NULL,
 PreparadoPor int NOT NULL,AprobadoPor int NOT NULL,
 FechaAprobacion datetime2 NOT NULL,
 PrincipalAprobador varbinary(85) NOT NULL,
 LoginAprobador nvarchar(128) NOT NULL,
 Comentario varchar(500) NOT NULL,
 CONSTRAINT CK_E201_Autorizacion_DosPersonas CHECK(AprobadoPor<>PreparadoPor)
);
IF OBJECT_ID('E201.RevocacionSSMS') IS NULL
CREATE TABLE E201.RevocacionSSMS(
 IdSolicitud bigint NOT NULL PRIMARY KEY REFERENCES E201.AutorizacionSSMS(IdSolicitud),
 Fecha datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
 LoginRevocador nvarchar(128) NOT NULL,
 Motivo varchar(500) NOT NULL
);

EXEC sys.sp_executesql N'
CREATE OR ALTER PROCEDURE E201.usp_AprobarCorteSSMS
 @IdPlan uniqueidentifier,@HashEsperado binary(32),@Comentario varchar(500)
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 IF COALESCE(IS_ROLEMEMBER(''E201_AprobadorCorte''),0)<>1
  THROW 56411,N''La identidad SQL actual no tiene permiso de aprobacion de corte.'',1;
 DECLARE @a int;
 SELECT @a=UsuarioID FROM E201.IdentidadCorte WHERE PrincipalSID=USER_SID()
 AND NombreLogin=ORIGINAL_LOGIN() AND Activo=1 AND AlcanceInstitucional=1;
 IF @a IS NULL THROW 56411,N''Aprobador no vinculado a contador vigente con alcance institucional.'',1;
 IF NULLIF(LTRIM(RTRIM(@Comentario)),'''') IS NULL THROW 56411,N''Comentario obligatorio.'',1;
 BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @j nvarchar(max),@h binary(32),@v binary(32),@actual binary(32),@p int,@sid varbinary(85),@login nvarchar(128);
 SELECT @j=Contenido,@h=HashPlan,@v=VersionObjetivo,@sid=PrincipalPreparador,@login=LoginPreparador
 FROM E201.PlanCorte WITH(UPDLOCK,HOLDLOCK) WHERE IdPlan=@IdPlan;
 SET @p=TRY_CONVERT(int,JSON_VALUE(@j,''$.PreparadoPor''));
 IF @p IS NULL OR @h<>@HashEsperado OR @HashEsperado IS NULL OR @h<>HASHBYTES(''SHA2_256'',@j)
  THROW 56413,N''Hash o plan distintos de lo revisado.'',1;
 IF @p=@a OR @sid=USER_SID() OR @login=ORIGINAL_LOGIN()
  THROW 56412,N''Autoaprobacion: requiere otro contador con otra identidad SQL autenticada.'',1;
 EXEC E201.usp_VersionObjetivo @actual OUTPUT;
 IF @v<>@actual THROW 56407,N''Objetivo cambio: preparar otro plan.'',1;
 INSERT E201.AutorizacionSSMS(IdPlan,HashPlan,PreparadoPor,AprobadoPor,FechaAprobacion,PrincipalAprobador,LoginAprobador,Comentario)
 VALUES(@IdPlan,@h,@p,@a,SYSUTCDATETIME(),USER_SID(),ORIGINAL_LOGIN(),@Comentario);
 DECLARE @IdSolicitud bigint=CONVERT(bigint,SCOPE_IDENTITY());
 /* Registrar y validar el recibo en la misma transaccion que la autorizacion. */
 EXEC E201.usp_RegistrarAprobacionReal @IdSolicitud,@IdPlan;
 COMMIT;
 SELECT @IdSolicitud AS IdSolicitud,@IdPlan AS IdPlan,''AUTORIZADA'' AS Resultado;
 END TRY BEGIN CATCH IF XACT_STATE()<>0 ROLLBACK; THROW; END CATCH;
END;
';
EXEC sys.sp_executesql N'
CREATE OR ALTER PROCEDURE E201.usp_ValidarAprobacionCorte
 @IdSolicitud bigint,@IdPlan uniqueidentifier,@HashPlan binary(32),
 @PreparadoPor int OUTPUT,@AprobadoPor int OUTPUT,@FechaAprobacion datetime2 OUTPUT
WITH EXECUTE AS OWNER
AS
BEGIN
 SET NOCOUNT ON;
 SELECT @PreparadoPor=NULL,@AprobadoPor=NULL,@FechaAprobacion=NULL;
 SELECT @PreparadoPor=a.PreparadoPor,@AprobadoPor=a.AprobadoPor,@FechaAprobacion=a.FechaAprobacion
 FROM E201.AutorizacionSSMS a WITH(HOLDLOCK) JOIN E201.PlanCorte p WITH(HOLDLOCK) ON p.IdPlan=a.IdPlan
 JOIN E201.IdentidadCorte ip WITH(HOLDLOCK) ON ip.PrincipalSID=p.PrincipalPreparador
 JOIN E201.IdentidadCorte ia WITH(HOLDLOCK) ON ia.PrincipalSID=a.PrincipalAprobador
 JOIN sys.database_principals pp ON pp.sid=ip.PrincipalSID
 JOIN sys.database_principals pa ON pa.sid=ia.PrincipalSID
 WHERE a.IdSolicitud=@IdSolicitud AND a.IdPlan=@IdPlan
 AND a.HashPlan=@HashPlan AND p.HashPlan=@HashPlan AND p.HashPlan=HASHBYTES(''SHA2_256'',p.Contenido)
 AND a.PreparadoPor=ip.UsuarioID AND a.AprobadoPor=ia.UsuarioID AND a.PreparadoPor<>a.AprobadoPor
 AND TRY_CONVERT(int,JSON_VALUE(p.Contenido,''$.PreparadoPor''))=a.PreparadoPor
 AND ip.Activo=1 AND ia.Activo=1 AND ip.AlcanceInstitucional=1 AND ia.AlcanceInstitucional=1
 AND ip.NombreLogin=p.LoginPreparador AND ia.NombreLogin=a.LoginAprobador
 AND p.LoginPreparador<>a.LoginAprobador AND p.PrincipalPreparador<>a.PrincipalAprobador
 AND COALESCE(IS_ROLEMEMBER(''E201_PreparadorCorte'',pp.name),0)=1
 AND COALESCE(IS_ROLEMEMBER(''E201_AprobadorCorte'',pa.name),0)=1
 AND NOT EXISTS(SELECT 1 FROM E201.RevocacionSSMS r WITH(HOLDLOCK) WHERE r.IdSolicitud=a.IdSolicitud);
 IF @PreparadoPor IS NULL OR @AprobadoPor IS NULL OR @FechaAprobacion IS NULL
  THROW 56414,N''Autorizacion real ausente, revocada, alterada o sin permiso efectivo actual.'',1;
END;
';
EXEC sys.sp_executesql N'
CREATE OR ALTER PROCEDURE E201.usp_RevocarCorteSSMS @IdSolicitud bigint,@Motivo varchar(500)
AS
BEGIN
 IF COALESCE(IS_ROLEMEMBER(''E201_AprobadorCorte''),0)<>1 OR NULLIF(LTRIM(RTRIM(@Motivo)),'''') IS NULL
  THROW 56411,N''Falta permiso de aprobacion o motivo.'',1;
 IF NOT EXISTS(SELECT 1 FROM E201.IdentidadCorte WHERE PrincipalSID=USER_SID()
 AND NombreLogin=ORIGINAL_LOGIN() AND Activo=1 AND AlcanceInstitucional=1)
  THROW 56411,N''Identidad de revocador no habilitada.'',1;
 INSERT E201.RevocacionSSMS(IdSolicitud,LoginRevocador,Motivo) VALUES(@IdSolicitud,ORIGINAL_LOGIN(),@Motivo);
END;
';
EXEC sys.sp_executesql N'
CREATE OR ALTER TRIGGER E201.trg_AutorizacionSSMS_Inmutable ON E201.AutorizacionSSMS AFTER UPDATE,DELETE AS
BEGIN THROW 56415,N''La autorizacion no se edita: registrar una revocacion.'',1; END;
';
EXEC sys.sp_executesql N'
CREATE OR ALTER TRIGGER E201.trg_RevocacionSSMS_Inmutable ON E201.RevocacionSSMS AFTER UPDATE,DELETE AS
BEGIN THROW 56415,N''La revocacion no se edita ni elimina.'',1; END;
';

GRANT EXECUTE ON E201.usp_PrepararCorte TO E201_PreparadorCorte;
GRANT SELECT ON E201.PlanCorte TO E201_AprobadorCorte;
GRANT EXECUTE ON E201.usp_AprobarCorteSSMS TO E201_AprobadorCorte;
GRANT EXECUTE ON E201.usp_RevocarCorteSSMS TO E201_AprobadorCorte;
/* Nadie recibe DML en identidad/autorizacion/recibos ni permisos de suplantacion.
   Solo el DBA vincula usuarios SQL EXISTENTES verificados. No se crean logins. */

/* LLAMADAS EN SESIONES/FASES SEPARADAS, despues de vincular identidades reales:
-- 1. Preparador: JSON completo del corte conciliado (formato en SSMS_CORTE.md).
DECLARE @IdPlan uniqueidentifier=NEWID(), @Contenido nvarchar(max)=N'<JSON DEL CORTE REAL>';
EXEC E201.usp_PrepararCorte @IdPlan=@IdPlan,@Contenido=@Contenido;
-- Otro contador revisa esos mismos bytes/hash y VersionObjetivo.

-- 2. OTRA conexion/login de contador con permiso especifico:
EXEC E201.usp_AprobarCorteSSMS @IdPlan='<ID_PLAN>',@HashEsperado=0x<HASH_REVISADO>,
 @Comentario='Corte revisado y conciliado';
-- Esta llamada emite, valida y registra el recibo real; devuelve IdSolicitud LOCAL.

-- 3. Ejecutar sin BEGIN TRAN externo. El procedimiento controla la transaccion:
EXEC E201.usp_EjecutarCorte @IdSolicitud=<ID_DEVUELTO>;
-- Reintentar con el MISMO IdSolicitud; devuelve el mismo asiento, no duplica.
*/

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
GO
CREATE OR ALTER PROCEDURE E201.usp_VersionObjetivo @Version binary(32) OUTPUT
AS
BEGIN
 DECLARE @j nvarchar(max)=(SELECT c.IdCuentaContable,c.CodigoCuenta,c.IdCuentaSuperior,
 c.Naturaleza,c.Estado,c.EsImputable,c.EsCuentaValuacion,c.SoloAutomatica,c.Saldo,
 c.FechaModificacion,s.SaldoPropio
 FROM Contabilidad.CuentasContables c JOIN E201.vw_SaldoPropio s ON s.IdCuentaContable=c.IdCuentaContable
 WHERE c.CodigoCuenta IN ('110105','210135','11010505','11010510','11010515','21013505','21013510')
 ORDER BY c.CodigoCuenta FOR JSON PATH);
 SET @Version=HASHBYTES('SHA2_256',@j);
END;
GO
CREATE OR ALTER PROCEDURE E201.usp_PrepararCorte
 @IdPlan uniqueidentifier,@Contenido nvarchar(max)
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 DECLARE @Usuario int;
 SELECT @Usuario=UsuarioID FROM E201.IdentidadCorte
 WHERE PrincipalSID=USER_SID() AND NombreLogin=ORIGINAL_LOGIN() AND Activo=1 AND AlcanceInstitucional=1;
 IF @Usuario IS NULL OR COALESCE(IS_ROLEMEMBER('E201_PreparadorCorte'),0)<>1
  THROW 56410,N'Preparador sin identidad de contador y permiso SQL efectivo.',1;
 IF ISJSON(@Contenido)<>1 THROW 56401,N'Plan JSON invalido.',1;
 IF TRY_CONVERT(uniqueidentifier,JSON_VALUE(@Contenido,'$.IdPlan'))<>@IdPlan
 OR JSON_VALUE(@Contenido,'$.IdPlan') IS NULL THROW 56401,N'IdPlan no coincide.',1;
 IF TRY_CONVERT(int,JSON_VALUE(@Contenido,'$.PreparadoPor'))<>@Usuario
 OR JSON_VALUE(@Contenido,'$.PreparadoPor') IS NULL
  THROW 56410,N'PreparadoPor no corresponde a la identidad SQL autenticada.',1;
 IF COALESCE(JSON_VALUE(@Contenido,'$.Alcance'),'')<>'EFECTIVO_AHORRO'
  THROW 56401,N'Este guion atomico requiere el corte completo de efectivo y ahorro.',1;
 IF EXISTS(SELECT 1 FROM E201.PlanCorte WHERE IdPlan=@IdPlan)
  THROW 56401,N'Plan ya congelado. No se edita; preparar una solicitud nueva.',1;
 DECLARE @v binary(32);
 EXEC E201.usp_VersionObjetivo @v OUTPUT;
 INSERT E201.PlanCorte(IdPlan,Contenido,HashPlan,VersionObjetivo,LoginPreparador,PrincipalPreparador)
 VALUES(@IdPlan,@Contenido,HASHBYTES('SHA2_256',@Contenido),@v,ORIGINAL_LOGIN(),USER_SID());
 SELECT IdPlan,Contenido,CONVERT(varchar(64),HashPlan,2) AS HashPlanSHA256_UTF16LE,
 CONVERT(varchar(64),VersionObjetivo,2) AS VersionObjetivo
 FROM E201.PlanCorte WHERE IdPlan=@IdPlan;
END;
GO
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
 IF OBJECT_ID('E201.usp_ValidarAprobacionCorte','P') IS NULL
  THROW 56402,N'Falta validador real del corte: no se emite recibo.',1;
 BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @j nvarchar(max),@h binary(32),@p int,@a int,@f datetime2;
 SELECT @j=Contenido,@h=HashPlan FROM E201.PlanCorte WITH(UPDLOCK,HOLDLOCK) WHERE IdPlan=@IdPlan;
 IF @j IS NULL OR @h<>HASHBYTES('SHA2_256',@j) THROW 56403,N'Plan ausente o alterado.',1;
 EXEC E201.usp_ValidarAprobacionCorte @IdSolicitud,@IdPlan,@h,@p OUTPUT,@a OUTPUT,@f OUTPUT;
 IF @p IS NULL OR @a IS NULL OR @p=@a OR @f IS NULL
 OR @p<>TRY_CONVERT(int,JSON_VALUE(@j,'$.PreparadoPor'))
  THROW 56404,N'Identidades de aprobacion invalidas o distintas del plan.',1;
 INSERT E201.ReciboReal VALUES(@IdSolicitud,@IdPlan,@p,@a,@f,@h,'AUTORIZADA',NULL);
 COMMIT;
 SELECT * FROM E201.ReciboReal WHERE IdSolicitud=@IdSolicitud;
 END TRY BEGIN CATCH IF XACT_STATE()<>0 ROLLBACK; THROW; END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE E201.usp_EjecutarCorte @IdSolicitud bigint
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 IF @@TRANCOUNT<>0 THROW 56405,N'Invocar sin transaccion previa.',1;
 IF OBJECT_ID('E201.usp_ValidarAprobacionCorte','P') IS NULL
  THROW 56402,N'Falta validador real del corte: corte no habilitado.',1;
 BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @plan uniqueidentifier,@j nvarchar(max),@h binary(32),@version binary(32),@actual binary(32),
 @p int,@a int,@f datetime2,@rp int,@ra int,@rf datetime2,@estado varchar(12),@asiento int,@corte uniqueidentifier,@fecha datetime2;
 SELECT @plan=IdPlan,@p=PreparadoPor,@a=AprobadoPor,@f=FechaAprobacion,@h=HashPlan,
 @estado=Estado,@asiento=IdAsientoContable FROM E201.ReciboReal WITH(UPDLOCK,HOLDLOCK) WHERE IdSolicitud=@IdSolicitud;
 IF @estado IS NULL THROW 56406,N'Recibo real no registrado.',1;
 IF @estado='EJECUTADA' BEGIN COMMIT; SELECT @asiento AS IdAsientoContable,'YA_EJECUTADA' AS Resultado; RETURN; END;
 SELECT @j=Contenido,@version=VersionObjetivo FROM E201.PlanCorte WITH(HOLDLOCK) WHERE IdPlan=@plan;
 IF @h<>HASHBYTES('SHA2_256',@j) THROW 56403,N'Contenido del plan alterado.',1;
 EXEC E201.usp_ValidarAprobacionCorte @IdSolicitud,@plan,@h,@rp OUTPUT,@ra OUTPUT,@rf OUTPUT;
 IF @rp IS NULL OR @ra IS NULL OR @rf IS NULL OR @rp<>@p OR @ra<>@a OR @rf<>@f OR @rp=@ra
  THROW 56404,N'Recibo revocado o identidades distintas.',1;
 DECLARE @n bigint;
 SELECT @n=COUNT_BIG(*) FROM Contabilidad.CuentasContables WITH(TABLOCKX,HOLDLOCK);
 SELECT @n=COUNT_BIG(*) FROM Contabilidad.MovimientosContables WITH(TABLOCKX,HOLDLOCK);
 EXEC E201.usp_VersionObjetivo @actual OUTPUT;
 IF @actual<>@version THROW 56407,N'Objetivo cambio desde la preparacion: solicitar nueva aprobacion.',1;
 SELECT @corte=TRY_CONVERT(uniqueidentifier,JSON_VALUE(@j,'$.IdCorte')),
 @fecha=TRY_CONVERT(datetime2,JSON_VALUE(@j,'$.FechaCorte'));
 IF @corte IS NULL OR @fecha IS NULL THROW 56401,N'Falta identificacion del corte.',1;
 /* 51100: padre no imputable ANTES de insertar hijas; aun SIN COMMIT. */
 EXEC E201.usp_AltaAuxiliaresEnCorte;
 INSERT E201.ControlCorte(IdCorte,CodigoAuxiliar,IdCustodio,FechaCorte,Monto,Fuente,Evidencia)
 SELECT @corte,CodigoAuxiliar,IdCustodio,@fecha,Monto,Fuente,Evidencia
 FROM OPENJSON(@j,'$.Controles') WITH(CodigoAuxiliar varchar(8),IdCustodio varchar(60),
 Monto decimal(18,2),Fuente varchar(250),Evidencia varchar(500));
 INSERT E201.ValidacionCorte
 SELECT @corte,@fecha,Libro210135,LibroPN,LibroPJ,OperativoPN,OperativoPJ,LineasSinMapeo,EsEnsayo,Evidencia
 FROM OPENJSON(@j,'$.ConciliacionAhorro') WITH(Libro210135 decimal(18,2),LibroPN decimal(18,2),LibroPJ decimal(18,2),
 OperativoPN decimal(18,2),OperativoPJ decimal(18,2),LineasSinMapeo int,EsEnsayo bit,Evidencia varchar(500));
 INSERT Contabilidad.AsientoContable
 (NumeroAsiento,FechaAsiento,FechaSistema,IdTipoAsiento,Origen,Concepto,TotalDebito,TotalCredito,
 Estado,IdUsuarioCreacion,IdAgencia,IdFechaContable)
 SELECT JSON_VALUE(@j,'$.NumeroAsiento'),CONVERT(date,@fecha),@fecha,t.IdTipoAsiento,'AJUSTE',
 'E201 corte aprobado por segunda persona',0,0,'BORRADOR',@p,JSON_VALUE(@j,'$.IdAgencia'),
 TRY_CONVERT(int,JSON_VALUE(@j,'$.IdFechaContable'))
 FROM Contabilidad.TiposAsiento t WHERE t.Codigo='MANUAL_RECLASIFICACION';
 SET @asiento=CONVERT(int,SCOPE_IDENTITY());
 INSERT E201.Reclasificacion
 (IdSolicitud,IdAsientoContable,IdCorte,PreparadoPor,AprobadoPor,FechaAprobacion,HashContenido,Estado,Alcance)
 VALUES(@IdSolicitud,@asiento,@corte,@p,@a,@f,0x00,'AUTORIZADA',JSON_VALUE(@j,'$.Alcance'));
 ;WITH destinos AS(
 SELECT c.IdCuentaContable,c.Naturaleza,c.IdCuentaSuperior,SUM(k.Monto) AS Monto
 FROM E201.ControlCorte k JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta=k.CodigoAuxiliar
 WHERE k.IdCorte=@corte GROUP BY c.IdCuentaContable,c.Naturaleza,c.IdCuentaSuperior HAVING SUM(k.Monto)>0
 ),lineas AS(
 SELECT IdCuentaContable,CASE Naturaleza WHEN 'DEUDORA' THEN 'DEBITO' ELSE 'CREDITO' END AS Lado,Monto FROM destinos
 UNION ALL SELECT p.IdCuentaContable,CASE p.Naturaleza WHEN 'DEUDORA' THEN 'CREDITO' ELSE 'DEBITO' END,SUM(d.Monto)
 FROM destinos d JOIN Contabilidad.CuentasContables p ON p.IdCuentaContable=d.IdCuentaSuperior
 GROUP BY p.IdCuentaContable,p.Naturaleza)
 INSERT E201.LineaReclasificacion
 SELECT @IdSolicitud,CONVERT(int,ROW_NUMBER() OVER(ORDER BY IdCuentaContable)),IdCuentaContable,Lado,Monto FROM lineas;
 EXEC E201.usp_HashInterno @IdSolicitud;
 /* Motor interno anida su transaccion. Su COMMIT NO confirma esta transaccion.
    Cualquier fallo revierte hijas, flags, controles, asiento y consumo juntos. */
 EXEC E201.usp_EjecutarReclasificacion @IdSolicitud;
 UPDATE E201.ReciboReal SET Estado='EJECUTADA',IdAsientoContable=@asiento WHERE IdSolicitud=@IdSolicitud;
 COMMIT;
 SELECT @asiento AS IdAsientoContable,'CORTE_EJECUTADO' AS Resultado;
 END TRY
 BEGIN CATCH IF XACT_STATE()<>0 ROLLBACK; THROW; END CATCH;
END;
GO
GRANT EXECUTE ON E201.usp_PrepararCorte TO E201_AdaptadorAprobacion;
GRANT EXECUTE ON E201.usp_RegistrarAprobacionReal TO E201_AdaptadorAprobacion;
GRANT EXECUTE ON E201.usp_EjecutarCorte TO E201_Ejecutor;
/* Sin permisos DML de negocio ni EXEC al motor/hash/alta internos para los roles. */

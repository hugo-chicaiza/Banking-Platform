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
GO
CREATE OR ALTER PROCEDURE E201.usp_AprobarCorteSSMS
 @IdPlan uniqueidentifier,@HashEsperado binary(32),@Comentario varchar(500)
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 IF COALESCE(IS_ROLEMEMBER('E201_AprobadorCorte'),0)<>1
  THROW 56411,N'La identidad SQL actual no tiene permiso de aprobacion de corte.',1;
 DECLARE @a int;
 SELECT @a=UsuarioID FROM E201.IdentidadCorte WHERE PrincipalSID=USER_SID()
 AND NombreLogin=ORIGINAL_LOGIN() AND Activo=1 AND AlcanceInstitucional=1;
 IF @a IS NULL THROW 56411,N'Aprobador no vinculado a contador vigente con alcance institucional.',1;
 IF NULLIF(LTRIM(RTRIM(@Comentario)),'') IS NULL THROW 56411,N'Comentario obligatorio.',1;
 BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @j nvarchar(max),@h binary(32),@v binary(32),@actual binary(32),@p int,@sid varbinary(85),@login nvarchar(128);
 SELECT @j=Contenido,@h=HashPlan,@v=VersionObjetivo,@sid=PrincipalPreparador,@login=LoginPreparador
 FROM E201.PlanCorte WITH(UPDLOCK,HOLDLOCK) WHERE IdPlan=@IdPlan;
 SET @p=TRY_CONVERT(int,JSON_VALUE(@j,'$.PreparadoPor'));
 IF @p IS NULL OR @h<>@HashEsperado OR @HashEsperado IS NULL OR @h<>HASHBYTES('SHA2_256',@j)
  THROW 56413,N'Hash o plan distintos de lo revisado.',1;
 IF @p=@a OR @sid=USER_SID() OR @login=ORIGINAL_LOGIN()
  THROW 56412,N'Autoaprobacion: requiere otro contador con otra identidad SQL autenticada.',1;
 EXEC E201.usp_VersionObjetivo @actual OUTPUT;
 IF @v<>@actual THROW 56407,N'Objetivo cambio: preparar otro plan.',1;
 INSERT E201.AutorizacionSSMS(IdPlan,HashPlan,PreparadoPor,AprobadoPor,FechaAprobacion,PrincipalAprobador,LoginAprobador,Comentario)
 VALUES(@IdPlan,@h,@p,@a,SYSUTCDATETIME(),USER_SID(),ORIGINAL_LOGIN(),@Comentario);
 DECLARE @IdSolicitud bigint=CONVERT(bigint,SCOPE_IDENTITY());
 /* Registrar y validar el recibo en la misma transaccion que la autorizacion. */
 EXEC E201.usp_RegistrarAprobacionReal @IdSolicitud,@IdPlan;
 COMMIT;
 SELECT @IdSolicitud AS IdSolicitud,@IdPlan AS IdPlan,'AUTORIZADA' AS Resultado;
 END TRY BEGIN CATCH IF XACT_STATE()<>0 ROLLBACK; THROW; END CATCH;
END;
GO
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
 AND a.HashPlan=@HashPlan AND p.HashPlan=@HashPlan AND p.HashPlan=HASHBYTES('SHA2_256',p.Contenido)
 AND a.PreparadoPor=ip.UsuarioID AND a.AprobadoPor=ia.UsuarioID AND a.PreparadoPor<>a.AprobadoPor
 AND TRY_CONVERT(int,JSON_VALUE(p.Contenido,'$.PreparadoPor'))=a.PreparadoPor
 AND ip.Activo=1 AND ia.Activo=1 AND ip.AlcanceInstitucional=1 AND ia.AlcanceInstitucional=1
 AND ip.NombreLogin=p.LoginPreparador AND ia.NombreLogin=a.LoginAprobador
 AND p.LoginPreparador<>a.LoginAprobador AND p.PrincipalPreparador<>a.PrincipalAprobador
 AND COALESCE(IS_ROLEMEMBER('E201_PreparadorCorte',pp.name),0)=1
 AND COALESCE(IS_ROLEMEMBER('E201_AprobadorCorte',pa.name),0)=1
 AND NOT EXISTS(SELECT 1 FROM E201.RevocacionSSMS r WITH(HOLDLOCK) WHERE r.IdSolicitud=a.IdSolicitud);
 IF @PreparadoPor IS NULL OR @AprobadoPor IS NULL OR @FechaAprobacion IS NULL
  THROW 56414,N'Autorizacion real ausente, revocada, alterada o sin permiso efectivo actual.',1;
END;
GO
CREATE OR ALTER PROCEDURE E201.usp_RevocarCorteSSMS @IdSolicitud bigint,@Motivo varchar(500)
AS
BEGIN
 IF COALESCE(IS_ROLEMEMBER('E201_AprobadorCorte'),0)<>1 OR NULLIF(LTRIM(RTRIM(@Motivo)),'') IS NULL
  THROW 56411,N'Falta permiso de aprobacion o motivo.',1;
 IF NOT EXISTS(SELECT 1 FROM E201.IdentidadCorte WHERE PrincipalSID=USER_SID()
 AND NombreLogin=ORIGINAL_LOGIN() AND Activo=1 AND AlcanceInstitucional=1)
  THROW 56411,N'Identidad de revocador no habilitada.',1;
 INSERT E201.RevocacionSSMS(IdSolicitud,LoginRevocador,Motivo) VALUES(@IdSolicitud,ORIGINAL_LOGIN(),@Motivo);
END;
GO
CREATE OR ALTER TRIGGER E201.trg_AutorizacionSSMS_Inmutable ON E201.AutorizacionSSMS AFTER UPDATE,DELETE AS
BEGIN THROW 56415,N'La autorizacion no se edita: registrar una revocacion.',1; END;
GO
CREATE OR ALTER TRIGGER E201.trg_RevocacionSSMS_Inmutable ON E201.RevocacionSSMS AFTER UPDATE,DELETE AS
BEGIN THROW 56415,N'La revocacion no se edita ni elimina.',1; END;
GO
GRANT EXECUTE ON E201.usp_PrepararCorte TO E201_PreparadorCorte;
GRANT SELECT ON E201.PlanCorte TO E201_AprobadorCorte;
GRANT EXECUTE ON E201.usp_AprobarCorteSSMS TO E201_AprobadorCorte;
GRANT EXECUTE ON E201.usp_RevocarCorteSSMS TO E201_AprobadorCorte;
/* Nadie recibe DML en identidad/autorizacion/recibos ni permisos de suplantacion.
   Solo el DBA vincula usuarios SQL EXISTENTES verificados. No se crean logins. */

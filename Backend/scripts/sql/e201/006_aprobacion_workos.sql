/* Instalar después de 004. Una identidad SQL privada del backend, dos personas WorkOS. */
IF DB_NAME()<>N'CooperativaDB' AND DB_NAME() NOT LIKE N'CooperativaDB_E201_Lab[_]%'
    THROW 56420,N'Base fuera del alcance E201.',1;
SET XACT_ABORT ON;
IF OBJECT_ID('E201.usp_EjecutarCorte','P') IS NULL
 OR OBJECT_ID('E201.usp_ValidarAprobacionCorte','P') IS NULL
    THROW 56420,N'Instale 004 antes de esta ampliación.',1;
BEGIN TRY
BEGIN TRANSACTION;
IF DATABASE_PRINCIPAL_ID('E201_ServicioWorkOS') IS NULL CREATE ROLE E201_ServicioWorkOS;
IF OBJECT_ID('E201.PermisoWorkOS','U') IS NULL
CREATE TABLE E201.PermisoWorkOS(
    UsuarioID int PRIMARY KEY REFERENCES Organizacion.Usuarios(UsuarioID),
    Preparar bit NOT NULL, Aprobar bit NOT NULL
);
IF OBJECT_ID('E201.PlanWorkOS','U') IS NULL
CREATE TABLE E201.PlanWorkOS(
    IdPlan uniqueidentifier PRIMARY KEY REFERENCES E201.PlanCorte(IdPlan),
    Preparador int NOT NULL,
    Sujeto varchar(128) COLLATE Latin1_General_100_BIN2 NOT NULL,
    Organizacion varchar(128) COLLATE Latin1_General_100_BIN2 NOT NULL
);
IF OBJECT_ID('E201.AutorizacionWorkOS','U') IS NULL
CREATE TABLE E201.AutorizacionWorkOS(
    IdSolicitud bigint IDENTITY(-1,-1) PRIMARY KEY,
    IdPlan uniqueidentifier NOT NULL UNIQUE REFERENCES E201.PlanWorkOS(IdPlan),
    HashPlan binary(32) NOT NULL,
    Aprobador int NOT NULL,
    Sujeto varchar(128) COLLATE Latin1_General_100_BIN2 NOT NULL,
    Fecha datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
    Comentario nvarchar(500) NOT NULL
);
IF OBJECT_ID('E201.usp_ValidarAprobacionSSMS','P') IS NULL
    EXEC sys.sp_rename 'E201.usp_ValidarAprobacionCorte','usp_ValidarAprobacionSSMS','OBJECT';

-- La rama positiva conserva exactamente el validador instalado por 004.
EXEC(N'
CREATE OR ALTER PROCEDURE E201.usp_ValidarAprobacionCorte
 @IdSolicitud bigint,@IdPlan uniqueidentifier,@HashPlan binary(32),
 @PreparadoPor int OUTPUT,@AprobadoPor int OUTPUT,@FechaAprobacion datetime2 OUTPUT
WITH EXECUTE AS OWNER
AS
BEGIN
 SET NOCOUNT ON;
 IF @IdSolicitud>0
 BEGIN
    EXEC E201.usp_ValidarAprobacionSSMS @IdSolicitud,@IdPlan,@HashPlan,
        @PreparadoPor OUTPUT,@AprobadoPor OUTPUT,@FechaAprobacion OUTPUT;
    RETURN;
 END;
 SELECT @PreparadoPor=NULL,@AprobadoPor=NULL,@FechaAprobacion=NULL;
 SELECT @PreparadoPor=w.Preparador,@AprobadoPor=a.Aprobador,@FechaAprobacion=a.Fecha
 FROM E201.AutorizacionWorkOS a WITH (HOLDLOCK)
 JOIN E201.PlanWorkOS w WITH (HOLDLOCK) ON w.IdPlan=a.IdPlan
 JOIN E201.PlanCorte p WITH (HOLDLOCK) ON p.IdPlan=w.IdPlan
 JOIN E201.PermisoWorkOS gp WITH (HOLDLOCK) ON gp.UsuarioID=w.Preparador AND gp.Preparar=1
 JOIN E201.PermisoWorkOS ga WITH (HOLDLOCK) ON ga.UsuarioID=a.Aprobador AND ga.Aprobar=1
 JOIN Organizacion.Usuarios ip WITH (HOLDLOCK) ON ip.UsuarioID=w.Preparador AND ip.Estado=''Activo''
 JOIN Organizacion.Usuarios ia WITH (HOLDLOCK) ON ia.UsuarioID=a.Aprobador AND ia.Estado=''Activo''
 WHERE a.IdSolicitud=@IdSolicitud AND a.IdPlan=@IdPlan
   AND a.HashPlan=@HashPlan AND p.HashPlan=@HashPlan AND p.HashPlan=HASHBYTES(''SHA2_256'',p.Contenido)
   AND ip.KeyUsuario COLLATE Latin1_General_100_BIN2=w.Sujeto
   AND ia.KeyUsuario COLLATE Latin1_General_100_BIN2=a.Sujeto
   AND w.Sujeto<>a.Sujeto AND w.Preparador<>a.Aprobador
   AND TRY_CONVERT(int,JSON_VALUE(p.Contenido,''$.PreparadoPor''))=w.Preparador;
 IF @PreparadoPor IS NULL OR @AprobadoPor IS NULL OR @FechaAprobacion IS NULL
    THROW 56414,N''Recibo institucional ausente, alterado o sin permiso efectivo.'',1;
END;');

EXEC(N'
CREATE OR ALTER PROCEDURE E201.usp_PlanWorkOS
 @Modo varchar(8),@Sujeto varchar(128),@Organizacion varchar(128),@IdPlan uniqueidentifier,
 @Contenido nvarchar(max)=NULL,@Hash binary(32)=NULL,@Comentario nvarchar(500)=NULL
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 IF COALESCE(IS_ROLEMEMBER(''E201_ServicioWorkOS''),0)<>1
    THROW 56420,N''La conexión no pertenece al servicio institucional.'',1;
 IF @Modo NOT IN (''PREPARAR'',''VER'',''APROBAR'') OR @Modo IS NULL OR NULLIF(@Organizacion,'''') IS NULL
    THROW 56420,N''Operación institucional inválida.'',1;
 BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @Actor int,@Cantidad int,@Version binary(32),@Actual binary(32),
         @HashPlan binary(32),@Preparador int,@SujetoPlan varchar(128),@IdSolicitud bigint;
 SELECT @Actor=MIN(u.UsuarioID),@Cantidad=COUNT(*)
 FROM Organizacion.Usuarios u WITH (HOLDLOCK)
 JOIN E201.PermisoWorkOS g WITH (HOLDLOCK) ON g.UsuarioID=u.UsuarioID
 WHERE u.KeyUsuario COLLATE Latin1_General_100_BIN2=@Sujeto AND u.Estado=''Activo''
   AND ((@Modo=''PREPARAR'' AND g.Preparar=1) OR (@Modo IN (''VER'',''APROBAR'') AND g.Aprobar=1));
 IF @Cantidad<>1 THROW 56411,N''Identidad institucional sin vínculo o permiso efectivo.'',1;
 IF @Modo=''PREPARAR''
 BEGIN
    IF COALESCE(ISJSON(@Contenido),0)<>1 OR COALESCE(JSON_VALUE(@Contenido,''$.Alcance''),'''')<>''EFECTIVO_AHORRO''
       THROW 56401,N''Plan de efectivo y ahorro inválido.'',1;
    SET @Contenido=JSON_MODIFY(JSON_MODIFY(@Contenido,''$.IdPlan'',CONVERT(varchar(36),@IdPlan)),''$.PreparadoPor'',@Actor);
    EXEC E201.usp_VersionObjetivo @Version OUTPUT;
    SET @HashPlan=HASHBYTES(''SHA2_256'',@Contenido);
    INSERT E201.PlanCorte(IdPlan,Contenido,HashPlan,VersionObjetivo,LoginPreparador,PrincipalPreparador)
    VALUES(@IdPlan,@Contenido,@HashPlan,@Version,ORIGINAL_LOGIN(),USER_SID());
    INSERT E201.PlanWorkOS(IdPlan,Preparador,Sujeto,Organizacion)
    VALUES(@IdPlan,@Actor,@Sujeto,@Organizacion);
 END
 ELSE
 BEGIN
    SELECT @Contenido=p.Contenido,@HashPlan=p.HashPlan,@Version=p.VersionObjetivo,
           @Preparador=w.Preparador,@SujetoPlan=w.Sujeto
    FROM E201.PlanCorte p WITH(UPDLOCK,HOLDLOCK)
    JOIN E201.PlanWorkOS w WITH(HOLDLOCK) ON w.IdPlan=p.IdPlan
    WHERE p.IdPlan=@IdPlan AND w.Organizacion=@Organizacion;
    IF @Preparador IS NULL THROW 56406,N''Plan institucional inexistente.'',1;
    IF @Modo=''APROBAR''
    BEGIN
       IF @Actor=@Preparador OR @Sujeto COLLATE Latin1_General_100_BIN2=@SujetoPlan
          THROW 56412,N''La aprobación requiere otra persona.'',1;
       IF @Hash IS NULL OR @Hash<>@HashPlan OR @HashPlan<>HASHBYTES(''SHA2_256'',@Contenido)
          THROW 56413,N''El hash no coincide con el plan revisado.'',1;
       IF NULLIF(LTRIM(RTRIM(@Comentario)),'''') IS NULL THROW 56411,N''Comentario obligatorio.'',1;
       EXEC E201.usp_VersionObjetivo @Actual OUTPUT;
       IF @Actual<>@Version THROW 56407,N''El objetivo cambió desde la preparación.'',1;
       IF EXISTS(SELECT 1 FROM E201.AutorizacionWorkOS WHERE IdPlan=@IdPlan)
          THROW 56413,N''El plan ya tiene autorización.'',1;
       INSERT E201.AutorizacionWorkOS(IdPlan,HashPlan,Aprobador,Sujeto,Comentario)
       VALUES(@IdPlan,@HashPlan,@Actor,@Sujeto,@Comentario);
       SET @IdSolicitud=CONVERT(bigint,SCOPE_IDENTITY());
       EXEC E201.usp_RegistrarAprobacionReal @IdSolicitud,@IdPlan;
    END;
 END;
 COMMIT;
 SELECT CONVERT(varchar(36),@IdPlan) IdPlan,@Contenido Contenido,
        CONVERT(varchar(64),@HashPlan,2) HashPlan,@IdSolicitud IdSolicitud;
 END TRY BEGIN CATCH IF XACT_STATE()<>0 ROLLBACK; THROW; END CATCH;
END;');
EXEC(N'CREATE OR ALTER TRIGGER E201.trg_PlanWorkOS_Inmutable ON E201.PlanWorkOS AFTER UPDATE,DELETE AS
BEGIN THROW 56415,N''El vínculo institucional del plan es inmutable.'',1; END;');
EXEC(N'CREATE OR ALTER TRIGGER E201.trg_AutorizacionWorkOS_Inmutable ON E201.AutorizacionWorkOS AFTER UPDATE,DELETE AS
BEGIN THROW 56415,N''La autorización institucional es inmutable.'',1; END;');
-- Las rutinas existentes verifican OBJECT_ID con la identidad del llamador.
GRANT VIEW DEFINITION ON OBJECT::E201.usp_ValidarAprobacionCorte TO E201_ServicioWorkOS;
GRANT VIEW DEFINITION ON OBJECT::E201.usp_ValidarAprobacionCorte TO E201_Ejecutor;
GRANT VIEW DEFINITION ON OBJECT::E201.usp_ValidarAprobacionCorte TO E201_AprobadorCorte;
GRANT VIEW DEFINITION ON OBJECT::E201.usp_ValidarAprobacionCorte TO E201_AdaptadorAprobacion;
-- Protege la fuente del recibo frente a permisos genéricos de escritura.
-- Los módulos del mismo propietario utilizan la cadena de propiedad.
DENY INSERT, UPDATE, DELETE ON E201.PlanWorkOS TO public;
DENY INSERT, UPDATE, DELETE ON E201.AutorizacionWorkOS TO public;
DENY INSERT, UPDATE, DELETE ON E201.PermisoWorkOS TO public;
GRANT EXECUTE ON E201.usp_PlanWorkOS TO E201_ServicioWorkOS;
COMMIT;
END TRY BEGIN CATCH IF XACT_STATE()<>0 ROLLBACK; THROW; END CATCH;

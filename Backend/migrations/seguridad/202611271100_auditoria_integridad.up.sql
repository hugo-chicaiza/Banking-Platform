/* E8-02 · Integridad y archivo de la bitácora (SeguridadDB). Aditiva salvo los dos disparadores que se amplían.
   - Cadena: Secuencia sin huecos, HashAnterior y Hash (SHA-256 del registro y del hash anterior, Auditoria.fn_HashRegistro).
     Auditoria.usp_RegistrarEvento es el único escritor encadenado: serializa con sp_getapplock hasta el commit, así un
     rollback no deja huecos. Las filas anteriores a esta migración quedan sin cadena (Secuencia NULL).
   - Archivo: Auditoria.AuditoriaArchivo y Auditoria.EventoDetalleArchivo con la misma estructura; las vistas
     vw_Bitacora y vw_EventoDetalle unen activa y archivo para el visor y la verificación.
     Un registro solo sale de la tabla activa si su copia idéntica ya está en el archivo y la sesión lo declara
     (SESSION_CONTEXT 'auditoria_archivo'); nunca se modifica. No hay purga (AU-8).
   - Auditoria.VerificacionIntegridad: resultado de cada verificación, con el hash del último eslabón como ancla.
   - Seguridad.LogTransacciones congelada (AU-4): sus filas quedan como historia.
   La app entra como dbo, así que DENY no la limita: los disparadores rechazan la escritura para cualquier login. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57206,'Falta confirmar la base destino de E8-02.',1;
IF DB_NAME()<>N'SeguridadDB' THROW 57206,'La migracion requiere SeguridadDB.',1;
BEGIN TRANSACTION;
BEGIN TRY
 IF COL_LENGTH('Auditoria.Auditoria','Secuencia') IS NULL
  ALTER TABLE Auditoria.Auditoria ADD Secuencia bigint NULL, HashAnterior binary(32) NULL, Hash binary(32) NULL;

 IF OBJECT_ID('Auditoria.AuditoriaArchivo','U') IS NULL
  CREATE TABLE Auditoria.AuditoriaArchivo(
   AuditoriaID int NOT NULL CONSTRAINT PK_AuditoriaArchivo PRIMARY KEY,
   UsuarioID int NULL, NombreAccion varchar(100) NOT NULL, TablaAfectada varchar(100) NULL, IDRegistro varchar(100) NULL,
   FechaHora datetime NOT NULL, DireccionIP varchar(45) NULL, Descripcion varchar(500) NULL, Resultado varchar(15) NOT NULL,
   RolesWorkOS varchar(200) NULL, IdEvento uniqueidentifier NULL, CodigoEvento varchar(100) NULL, FechaHoraUTC datetime2 NULL,
   IdAgencia char(3) NULL, IdSesion varchar(64) NULL, Canal varchar(10) NULL, IdCorrelacion varchar(64) NULL,
   TipoObjetivo varchar(100) NULL, IdObjetivo varchar(100) NULL, Cambios nvarchar(max) NULL, FormatoAnterior bit NOT NULL,
   Secuencia bigint NULL, HashAnterior binary(32) NULL, Hash binary(32) NULL);
 IF OBJECT_ID('Auditoria.EventoDetalleArchivo','U') IS NULL
  CREATE TABLE Auditoria.EventoDetalleArchivo(
   IdEvento uniqueidentifier NOT NULL CONSTRAINT PK_EventoDetalleArchivo PRIMARY KEY,
   AuditoriaID int NOT NULL CONSTRAINT UQ_EventoDetalleArchivo_Auditoria UNIQUE,
   CodigoEvento varchar(40) NOT NULL, Contenido nvarchar(max) NOT NULL, FechaHoraUTC datetime2(7) NOT NULL);
 IF OBJECT_ID('Auditoria.VerificacionIntegridad','U') IS NULL
  CREATE TABLE Auditoria.VerificacionIntegridad(
   IdVerificacion bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_VerificacionIntegridad PRIMARY KEY,
   SecuenciaDesde bigint NOT NULL, SecuenciaHasta bigint NOT NULL,
   Resultado varchar(10) NOT NULL CONSTRAINT CK_Verificacion_Resultado CHECK (Resultado IN ('Integra','Rota')),
   PrimeraRota bigint NULL, HashHasta binary(32) NULL,
   EjecutadaPor int NULL, -- NULL = tarea nocturna
   FechaUTC datetime2 NOT NULL CONSTRAINT DF_Verificacion_Fecha DEFAULT (SYSUTCDATETIME()));

 IF INDEXPROPERTY(OBJECT_ID('Auditoria.Auditoria'),'UX_Auditoria_Secuencia','IndexID') IS NULL
  EXEC('CREATE UNIQUE INDEX UX_Auditoria_Secuencia ON Auditoria.Auditoria(Secuencia) WHERE Secuencia IS NOT NULL');
 IF INDEXPROPERTY(OBJECT_ID('Auditoria.AuditoriaArchivo'),'UX_AuditoriaArchivo_Secuencia','IndexID') IS NULL
  EXEC('CREATE UNIQUE INDEX UX_AuditoriaArchivo_Secuencia ON Auditoria.AuditoriaArchivo(Secuencia) WHERE Secuencia IS NOT NULL');
 IF INDEXPROPERTY(OBJECT_ID('Auditoria.AuditoriaArchivo'),'IX_AuditoriaArchivo_FechaUTC','IndexID') IS NULL
  EXEC('CREATE INDEX IX_AuditoriaArchivo_FechaUTC ON Auditoria.AuditoriaArchivo(FechaHoraUTC)');

 /* Hash v1: cada campo como "largo:valor|" (NULL = "~|"), así ningún valor se confunde con el siguiente */
 EXEC(N'CREATE OR ALTER FUNCTION Auditoria.fn_HashRegistro(
   @Secuencia bigint, @HashAnterior binary(32), @IdEvento uniqueidentifier, @CodigoEvento varchar(100),
   @NombreAccion varchar(100), @FechaHoraUTC datetime2, @FechaHora datetime, @UsuarioID int, @TablaAfectada varchar(100),
   @IDRegistro varchar(100), @DireccionIP varchar(45), @Descripcion varchar(500), @Resultado varchar(15),
   @RolesWorkOS varchar(200), @IdAgencia char(3), @IdSesion varchar(64), @Canal varchar(10), @IdCorrelacion varchar(64),
   @TipoObjetivo varchar(100), @IdObjetivo varchar(100), @Cambios nvarchar(max), @FormatoAnterior bit)
  RETURNS binary(32) WITH SCHEMABINDING AS
  BEGIN
   RETURN CONVERT(binary(32), HASHBYTES(''SHA2_256'', CONCAT(N''v1|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@Secuencia)))+N'':''+CONVERT(nvarchar(max),@Secuencia),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@HashAnterior,2)))+N'':''+CONVERT(nvarchar(max),@HashAnterior,2),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@IdEvento)))+N'':''+CONVERT(nvarchar(max),@IdEvento),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@CodigoEvento)))+N'':''+CONVERT(nvarchar(max),@CodigoEvento),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@NombreAccion)))+N'':''+CONVERT(nvarchar(max),@NombreAccion),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@FechaHoraUTC,121)))+N'':''+CONVERT(nvarchar(max),@FechaHoraUTC,121),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@FechaHora,121)))+N'':''+CONVERT(nvarchar(max),@FechaHora,121),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@UsuarioID)))+N'':''+CONVERT(nvarchar(max),@UsuarioID),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@TablaAfectada)))+N'':''+CONVERT(nvarchar(max),@TablaAfectada),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@IDRegistro)))+N'':''+CONVERT(nvarchar(max),@IDRegistro),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@DireccionIP)))+N'':''+CONVERT(nvarchar(max),@DireccionIP),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@Descripcion)))+N'':''+CONVERT(nvarchar(max),@Descripcion),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@Resultado)))+N'':''+CONVERT(nvarchar(max),@Resultado),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@RolesWorkOS)))+N'':''+CONVERT(nvarchar(max),@RolesWorkOS),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@IdAgencia)))+N'':''+CONVERT(nvarchar(max),@IdAgencia),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@IdSesion)))+N'':''+CONVERT(nvarchar(max),@IdSesion),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@Canal)))+N'':''+CONVERT(nvarchar(max),@Canal),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@IdCorrelacion)))+N'':''+CONVERT(nvarchar(max),@IdCorrelacion),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@TipoObjetivo)))+N'':''+CONVERT(nvarchar(max),@TipoObjetivo),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@IdObjetivo)))+N'':''+CONVERT(nvarchar(max),@IdObjetivo),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@Cambios)))+N'':''+CONVERT(nvarchar(max),@Cambios),N''~''),N''|'',
    COALESCE(CONVERT(nvarchar(max),DATALENGTH(CONVERT(nvarchar(max),@FormatoAnterior)))+N'':''+CONVERT(nvarchar(max),@FormatoAnterior),N''~''),N''|'')));
  END');

 EXEC(N'CREATE OR ALTER VIEW Auditoria.vw_Bitacora AS
  SELECT AuditoriaID, UsuarioID, NombreAccion, TablaAfectada, IDRegistro, FechaHora, DireccionIP, Descripcion, Resultado,
         RolesWorkOS, IdEvento, CodigoEvento, FechaHoraUTC, IdAgencia, IdSesion, Canal, IdCorrelacion, TipoObjetivo,
         IdObjetivo, Cambios, FormatoAnterior, Secuencia, HashAnterior, Hash, CONVERT(bit, 0) AS Archivado
  FROM Auditoria.Auditoria
  UNION ALL
  SELECT AuditoriaID, UsuarioID, NombreAccion, TablaAfectada, IDRegistro, FechaHora, DireccionIP, Descripcion, Resultado,
         RolesWorkOS, IdEvento, CodigoEvento, FechaHoraUTC, IdAgencia, IdSesion, Canal, IdCorrelacion, TipoObjetivo,
         IdObjetivo, Cambios, FormatoAnterior, Secuencia, HashAnterior, Hash, CONVERT(bit, 1)
  FROM Auditoria.AuditoriaArchivo');
 EXEC(N'CREATE OR ALTER VIEW Auditoria.vw_EventoDetalle AS
  SELECT IdEvento, AuditoriaID, CodigoEvento, Contenido, FechaHoraUTC FROM Auditoria.EventoDetalle
  UNION ALL
  SELECT IdEvento, AuditoriaID, CodigoEvento, Contenido, FechaHoraUTC FROM Auditoria.EventoDetalleArchivo');

 EXEC(N'CREATE OR ALTER PROCEDURE Auditoria.usp_RegistrarEvento
   @UsuarioID int, @NombreAccion varchar(100), @TablaAfectada varchar(100), @IDRegistro varchar(100),
   @DireccionIP varchar(45), @Descripcion varchar(500), @Resultado varchar(15), @RolesWorkOS varchar(200),
   @IdEvento uniqueidentifier = NULL, @CodigoEvento varchar(100) = NULL, @FechaHoraUTC datetime2 = NULL,
   @IdAgencia char(3) = NULL, @IdSesion varchar(64) = NULL, @Canal varchar(10) = NULL, @IdCorrelacion varchar(64) = NULL,
   @TipoObjetivo varchar(100) = NULL, @IdObjetivo varchar(100) = NULL, @Cambios nvarchar(max) = NULL,
   @AuditoriaID int = NULL OUTPUT
  AS
  BEGIN
   SET NOCOUNT ON; SET XACT_ABORT ON;
   DECLARE @propia bit = CASE WHEN @@TRANCOUNT = 0 THEN 1 ELSE 0 END, @r int;
   IF @propia = 1 BEGIN TRANSACTION;
   -- Hasta el commit de quien registra: la siguiente secuencia espera y un rollback no deja huecos
   EXEC @r = sys.sp_getapplock @Resource = N''Auditoria.Cadena'', @LockMode = ''Exclusive'', @LockOwner = ''Transaction'', @LockTimeout = 15000;
   IF @r < 0 THROW 57210, N''No se pudo encadenar el registro de auditoría.'', 1;
   DECLARE @utc datetime2 = COALESCE(@FechaHoraUTC, SYSUTCDATETIME());
   DECLARE @local datetime = CONVERT(datetime, DATEADD(hour, -5, @utc)); -- Ecuador, UTC-5 sin verano
   DECLARE @evento uniqueidentifier = COALESCE(@IdEvento, NEWID()), @secuencia bigint, @anterior binary(32);
   IF @RolesWorkOS IS NULL AND @UsuarioID IS NOT NULL
    SELECT @RolesWorkOS = u.RolesWorkOS FROM Organizacion.Usuarios AS u WHERE u.UsuarioID = @UsuarioID;
   SELECT TOP (1) @secuencia = Secuencia, @anterior = Hash FROM Auditoria.vw_Bitacora
   WHERE Secuencia IS NOT NULL ORDER BY Secuencia DESC;
   SET @secuencia = COALESCE(@secuencia, 0) + 1;
   INSERT Auditoria.Auditoria(UsuarioID, NombreAccion, TablaAfectada, IDRegistro, FechaHora, DireccionIP, Descripcion,
     Resultado, RolesWorkOS, IdEvento, CodigoEvento, FechaHoraUTC, IdAgencia, IdSesion, Canal, IdCorrelacion,
     TipoObjetivo, IdObjetivo, Cambios, FormatoAnterior, Secuencia, HashAnterior, Hash)
   VALUES (@UsuarioID, @NombreAccion, @TablaAfectada, @IDRegistro, @local, @DireccionIP, @Descripcion, @Resultado,
     @RolesWorkOS, @evento, @CodigoEvento, @utc, @IdAgencia, @IdSesion, @Canal, @IdCorrelacion, @TipoObjetivo, @IdObjetivo,
     @Cambios, 0, @secuencia, @anterior,
     Auditoria.fn_HashRegistro(@secuencia, @anterior, @evento, @CodigoEvento, @NombreAccion, @utc, @local, @UsuarioID,
       @TablaAfectada, @IDRegistro, @DireccionIP, @Descripcion, @Resultado, @RolesWorkOS, @IdAgencia, @IdSesion, @Canal,
       @IdCorrelacion, @TipoObjetivo, @IdObjetivo, @Cambios, 0));
   SET @AuditoriaID = CONVERT(int, SCOPE_IDENTITY());
   IF @propia = 1 COMMIT TRANSACTION;
  END');

 /* Solo inserción; la única salida es pasar al archivo con una copia idéntica (nunca UPDATE) */
 EXEC(N'CREATE OR ALTER TRIGGER Auditoria.trg_Auditoria_SoloInsercion ON Auditoria.Auditoria AFTER UPDATE, DELETE AS
  BEGIN
   SET NOCOUNT ON;
   IF EXISTS (SELECT 1 FROM inserted)
      OR COALESCE(CONVERT(int, SESSION_CONTEXT(N''auditoria_archivo'')), 0) <> 1
      OR EXISTS (SELECT AuditoriaID, UsuarioID, NombreAccion, TablaAfectada, IDRegistro, FechaHora, DireccionIP, Descripcion,
                        Resultado, RolesWorkOS, IdEvento, CodigoEvento, FechaHoraUTC, IdAgencia, IdSesion, Canal,
                        IdCorrelacion, TipoObjetivo, IdObjetivo, Cambios, FormatoAnterior, Secuencia, HashAnterior, Hash
                 FROM deleted
                 EXCEPT
                 SELECT AuditoriaID, UsuarioID, NombreAccion, TablaAfectada, IDRegistro, FechaHora, DireccionIP, Descripcion,
                        Resultado, RolesWorkOS, IdEvento, CodigoEvento, FechaHoraUTC, IdAgencia, IdSesion, Canal,
                        IdCorrelacion, TipoObjetivo, IdObjetivo, Cambios, FormatoAnterior, Secuencia, HashAnterior, Hash
                 FROM Auditoria.AuditoriaArchivo)
    THROW 57201, N''La bitácora de auditoría no se modifica ni se elimina.'', 1;
  END');
 EXEC(N'CREATE OR ALTER TRIGGER Auditoria.trg_ED_E008_Inmutable ON Auditoria.EventoDetalle AFTER UPDATE, DELETE AS
  BEGIN
   SET NOCOUNT ON;
   IF EXISTS (SELECT 1 FROM inserted)
      OR COALESCE(CONVERT(int, SESSION_CONTEXT(N''auditoria_archivo'')), 0) <> 1
      OR EXISTS (SELECT IdEvento, AuditoriaID, CodigoEvento, Contenido, FechaHoraUTC FROM deleted
                 EXCEPT SELECT IdEvento, AuditoriaID, CodigoEvento, Contenido, FechaHoraUTC FROM Auditoria.EventoDetalleArchivo)
    THROW 57201, ''El detalle de auditoria es inmutable.'', 1;
  END');
 EXEC(N'CREATE OR ALTER TRIGGER Auditoria.trg_AuditoriaArchivo_Inmutable ON Auditoria.AuditoriaArchivo AFTER UPDATE, DELETE AS
  BEGIN SET NOCOUNT ON; THROW 57201, N''El archivo de la bitácora no se modifica ni se elimina.'', 1; END');
 EXEC(N'CREATE OR ALTER TRIGGER Auditoria.trg_EventoDetalleArchivo_Inmutable ON Auditoria.EventoDetalleArchivo AFTER UPDATE, DELETE AS
  BEGIN SET NOCOUNT ON; THROW 57201, N''El archivo del detalle de auditoría es inmutable.'', 1; END');
 EXEC(N'CREATE OR ALTER TRIGGER Auditoria.trg_VerificacionIntegridad_Inmutable ON Auditoria.VerificacionIntegridad AFTER UPDATE, DELETE AS
  BEGIN SET NOCOUNT ON; THROW 57201, N''Las verificaciones de integridad no se modifican ni se eliminan.'', 1; END');
 EXEC(N'CREATE OR ALTER TRIGGER Seguridad.trg_LogTransacciones_Congelada ON Seguridad.LogTransacciones INSTEAD OF INSERT, UPDATE, DELETE AS
  BEGIN SET NOCOUNT ON; THROW 57202, N''LogTransacciones está retirada (AU-4): sus filas quedan como historia.'', 1; END');

 INSERT Auditoria.TipoEvento (CodigoEvento, Modulo, Severidad, EnTransaccion)
 SELECT e.CodigoEvento, e.Modulo, e.Severidad, e.EnTransaccion
 FROM (VALUES ('AUD_INTEGRIDAD_ROTA', 'auditoria', 'Seguridad', 0),
              ('AUD_ARCHIVO', 'auditoria', 'Sensible', 0))
     AS e(CodigoEvento, Modulo, Severidad, EnTransaccion)
 WHERE NOT EXISTS (SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK) WHERE CodigoEvento = e.CodigoEvento);

 -- El archivo es anual: sin ventana, el vigilante no lo da por atrasado entre ejecuciones
 INSERT Sistema.Tarea (Codigo, Descripcion, Modulo, Programacion, PermiteManual, VentanaEsperadaMin)
 SELECT t.Codigo, t.Descripcion, t.Modulo, t.Programacion, t.PermiteManual, t.Ventana
 FROM (VALUES ('AUD_VERIFICAR_INTEGRIDAD', N'Verifica la cadena de la bitácora del día anterior', 'Auditoria', 'diaria', 1, 1500),
              ('AUD_ARCHIVAR', N'Mueve al archivo los registros de la bitácora más antiguos que AUD_EDAD_ARCHIVO_ANIOS', 'Auditoria', 'anual', 1, NULL))
     AS t(Codigo, Descripcion, Modulo, Programacion, PermiteManual, Ventana)
 WHERE NOT EXISTS (SELECT 1 FROM Sistema.Tarea WITH (UPDLOCK, HOLDLOCK) WHERE Codigo = t.Codigo);
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;

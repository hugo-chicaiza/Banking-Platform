-- E3-03: migracion propuesta; validar primero en laboratorio local propio.
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
    THROW 57603,'Falta confirmar la base destino de E3-03.',1;
IF CONVERT(int,SERVERPROPERTY('EngineEdition'))=5 AND ISNULL(CONVERT(int,SESSION_CONTEXT(N'E303_AZURE_APROBADA')),0)<>1
    THROW 57603,'E3-03 requiere autorizacion adicional para Azure.',1;
BEGIN TRY
    BEGIN TRANSACTION;
    IF OBJECT_ID(N'ProductosFinancieros.ProductoRestriccion',N'U') IS NULL
       OR OBJECT_ID(N'ProductosFinancieros.TipoRestriccion',N'U') IS NULL
        THROW 57603, 'Faltan objetos E3-01; no se crean sustitutos.', 1;

    /* El indice actual impide mas de una fila A por tipo, aunque no solapen.
       Se reemplaza por unicidad de inicio + trigger de exclusion temporal.
       No se elimina ninguna restriccion ni se convierten sus tipos almacenados.
    */
    IF EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'ProductosFinancieros.ProductoRestriccion') AND name=N'UX_ProductoRestriccion_Activa')
        DROP INDEX UX_ProductoRestriccion_Activa ON ProductosFinancieros.ProductoRestriccion;
    IF COL_LENGTH(N'ProductosFinancieros.ProductoRestriccion',N'TipoRestriccion') = 20
        ALTER TABLE ProductosFinancieros.ProductoRestriccion ALTER COLUMN TipoRestriccion varchar(30) NOT NULL;
    ELSE IF COL_LENGTH(N'ProductosFinancieros.ProductoRestriccion',N'TipoRestriccion') <> 30
        THROW 57603, 'Longitud inesperada de TipoRestriccion.', 1;
    IF COL_LENGTH(N'ProductosFinancieros.ProductoRestriccion',N'Cantidad') IS NULL
        ALTER TABLE ProductosFinancieros.ProductoRestriccion ADD Cantidad smallint NULL;
    IF COL_LENGTH(N'ProductosFinancieros.ProductoRestriccion',N'IdSolicitud') IS NULL
        ALTER TABLE ProductosFinancieros.ProductoRestriccion ADD IdSolicitud bigint NULL;

    IF OBJECT_ID(N'ProductosFinancieros.CK_ProductoRestriccion_Tipo',N'C') IS NOT NULL
        ALTER TABLE ProductosFinancieros.ProductoRestriccion DROP CONSTRAINT CK_ProductoRestriccion_Tipo;
    EXEC sys.sp_executesql N'ALTER TABLE ProductosFinancieros.ProductoRestriccion WITH CHECK ADD CONSTRAINT CK_ProductoRestriccion_Tipo CHECK (
       (TipoRestriccion=''SIN_RETIROS'' AND Monto IS NULL AND Cantidad IS NULL AND (Dias IS NULL OR Dias>0))
       OR (TipoRestriccion=''SIN_RETIROS_DIAS'' AND Dias>0 AND Dias IS NOT NULL AND Monto IS NULL AND Cantidad IS NULL)
       OR (TipoRestriccion IN (''SALDO_MINIMO'',''SALDO_MAXIMO'') AND Monto>0 AND Monto IS NOT NULL AND Dias IS NULL AND Cantidad IS NULL)
       OR (TipoRestriccion=''MAXIMO_CUENTAS_CLIENTE'' AND Cantidad>0 AND Cantidad IS NOT NULL AND Dias IS NULL AND Monto IS NULL)
       OR (TipoRestriccion=''SIN_TRANSFERENCIAS_SALIDA'' AND Dias IS NULL AND Monto IS NULL AND Cantidad IS NULL)
    )';
    /* SIN_RETIROS con Dias se conserva como formato legado de SIN_RETIROS_DIAS.
       Los registros nuevos se validan contra TipoRestriccion.UsaDias/Monto/Cantidad.
    */
    IF OBJECT_ID(N'ProductosFinancieros.CK_ProductoRestriccion_Vigencia',N'C') IS NOT NULL
        ALTER TABLE ProductosFinancieros.ProductoRestriccion DROP CONSTRAINT CK_ProductoRestriccion_Vigencia;
    ALTER TABLE ProductosFinancieros.ProductoRestriccion WITH CHECK ADD CONSTRAINT CK_ProductoRestriccion_Vigencia CHECK(VigenciaHasta IS NULL OR VigenciaHasta>=VigenciaDesde);
    IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'ProductosFinancieros.ProductoRestriccion') AND name=N'UX_E303_Restriccion_Inicio')
        CREATE UNIQUE INDEX UX_E303_Restriccion_Inicio ON ProductosFinancieros.ProductoRestriccion(IdSubProducto,TipoRestriccion,VigenciaDesde) WHERE Estado='A';

    EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER ProductosFinancieros.trg_SubProductoCondicion_SinSolape
    ON ProductosFinancieros.SubProductoCondicion AFTER INSERT, UPDATE AS
    BEGIN
        SET NOCOUNT ON;
        DECLARE @id int;
        SELECT @id=s.IdSubProducto FROM ProductosFinancieros.SubProducto s WITH(UPDLOCK,HOLDLOCK)
        WHERE s.IdSubProducto IN(SELECT IdSubProducto FROM inserted) ORDER BY s.IdSubProducto;
        IF EXISTS(SELECT 1 FROM inserted i JOIN ProductosFinancieros.SubProductoCondicion v WITH(UPDLOCK,HOLDLOCK)
          ON v.IdSubProducto=i.IdSubProducto AND v.IdCondicion<>i.IdCondicion
          AND v.Estado IN(''Programada'',''Vigente'') AND i.Estado IN(''Programada'',''Vigente'')
          AND v.VigenciaDesde<=ISNULL(i.VigenciaHasta,CONVERT(date,''99991231'',112))
          AND i.VigenciaDesde<=ISNULL(v.VigenciaHasta,CONVERT(date,''99991231'',112)))
            THROW 56201,''VIGENCIA_SOLAPADA: condiciones del subproducto.'',1;
    END';
    EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER ProductosFinancieros.trg_ProductoCanalCupo_SinSolape
    ON ProductosFinancieros.ProductoCanalCupo AFTER INSERT, UPDATE AS
    BEGIN
        SET NOCOUNT ON;
        DECLARE @id int;
        SELECT @id=s.IdSubProducto FROM ProductosFinancieros.SubProducto s WITH(UPDLOCK,HOLDLOCK)
        WHERE s.IdSubProducto IN(SELECT IdSubProducto FROM inserted) ORDER BY s.IdSubProducto;
        IF EXISTS(SELECT 1 FROM inserted i JOIN ProductosFinancieros.ProductoCanalCupo v WITH(UPDLOCK,HOLDLOCK)
          ON v.IdSubProducto=i.IdSubProducto AND v.IdCanal=i.IdCanal AND v.IdProductoCanalCupo<>i.IdProductoCanalCupo
          AND v.EstadoCupo=''A'' AND i.EstadoCupo=''A''
          AND v.VigenciaDesde<=ISNULL(i.VigenciaHasta,CONVERT(date,''99991231'',112))
          AND i.VigenciaDesde<=ISNULL(v.VigenciaHasta,CONVERT(date,''99991231'',112)))
            THROW 56202,''VIGENCIA_SOLAPADA: cupos del canal.'',1;
    END';
    EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER ProductosFinancieros.trg_ProductoRestriccion_SinSolape
    ON ProductosFinancieros.ProductoRestriccion AFTER INSERT, UPDATE AS
    BEGIN
        SET NOCOUNT ON;
        DECLARE @id int;
        SELECT @id=s.IdSubProducto FROM ProductosFinancieros.SubProducto s WITH(UPDLOCK,HOLDLOCK)
        WHERE s.IdSubProducto IN(SELECT IdSubProducto FROM inserted) ORDER BY s.IdSubProducto;
        IF EXISTS(SELECT 1 FROM inserted i JOIN ProductosFinancieros.ProductoRestriccion v WITH(UPDLOCK,HOLDLOCK)
          ON v.IdSubProducto=i.IdSubProducto AND v.IdRestriccion<>i.IdRestriccion
          AND (CASE WHEN v.TipoRestriccion=''SIN_RETIROS'' AND v.Dias IS NOT NULL THEN ''SIN_RETIROS_DIAS'' ELSE v.TipoRestriccion END)
            =(CASE WHEN i.TipoRestriccion=''SIN_RETIROS'' AND i.Dias IS NOT NULL THEN ''SIN_RETIROS_DIAS'' ELSE i.TipoRestriccion END)
          AND v.Estado=''A'' AND i.Estado=''A''
          AND v.VigenciaDesde<=ISNULL(i.VigenciaHasta,CONVERT(date,''99991231'',112))
          AND i.VigenciaDesde<=ISNULL(v.VigenciaHasta,CONVERT(date,''99991231'',112)))
            THROW 56203,''VIGENCIA_SOLAPADA: restricciones del mismo tipo.'',1;
    END';
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

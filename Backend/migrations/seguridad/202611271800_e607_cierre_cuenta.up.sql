SET NOCOUNT ON;
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57730, 'Falta confirmar la base destino de E6-07.', 1;
IF OBJECT_ID(N'Seguridad.TransaccionesInterfaz', N'U') IS NULL
   OR OBJECT_ID(N'Auditoria.TipoEvento', N'U') IS NULL
    THROW 57730, 'Faltan el catálogo de operaciones o el catálogo de auditoría.', 1;

BEGIN TRANSACTION;
IF OBJECT_ID(N'Seguridad.E607CatalogoPropiedad', N'U') IS NULL
    CREATE TABLE Seguridad.E607CatalogoPropiedad (
        CodigoObjeto varchar(32) NOT NULL,
        Codigo nvarchar(100) NOT NULL,
        CONSTRAINT PK_E607CatalogoPropiedad PRIMARY KEY (CodigoObjeto, Codigo)
    );

IF EXISTS (
    SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoTransaccion='CTA-CERRAR'
      AND (Modulo<>'Cuentas' OR BaseObjetivo<>'cooperativa'
           OR RolesEjecucion<>N'["ADMIN","ASESOR"]'
           OR PermisoAprobacion<>'cuentas:aprobar' OR EsSensible<>1 OR Estado<>'A')
)
    THROW 57730, 'La operación CTA-CERRAR existente es incompatible.', 1;
IF NOT EXISTS (
    SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoTransaccion='CTA-CERRAR'
)
BEGIN
    INSERT Seguridad.TransaccionesInterfaz
        (CodigoTransaccion,NombreTransaccion,Modulo,BaseObjetivo,RolesEjecucion,
         PermisoAprobacion,EsSensible,Estado)
    VALUES
        ('CTA-CERRAR',N'Solicitar cierre de cuenta','Cuentas','cooperativa',
         N'["ADMIN","ASESOR"]','cuentas:aprobar',1,'A');
    IF NOT EXISTS (
        SELECT 1 FROM Seguridad.E607CatalogoPropiedad
        WHERE CodigoObjeto='TransaccionesInterfaz' AND Codigo='CTA-CERRAR'
    )
        INSERT Seguridad.E607CatalogoPropiedad (CodigoObjeto,Codigo)
        VALUES ('TransaccionesInterfaz','CTA-CERRAR');
END;

IF EXISTS (
    SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoEvento='CTA_CIERRE'
      AND (Modulo<>'cuentas' OR Severidad<>'Sensible' OR EnTransaccion<>1)
)
    THROW 57730, 'El evento CTA_CIERRE existente es incompatible.', 1;
IF NOT EXISTS (
    SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoEvento='CTA_CIERRE'
)
BEGIN
    INSERT Auditoria.TipoEvento (CodigoEvento,Modulo,Severidad,EnTransaccion)
    VALUES ('CTA_CIERRE','cuentas','Sensible',1);
    IF NOT EXISTS (
        SELECT 1 FROM Seguridad.E607CatalogoPropiedad
        WHERE CodigoObjeto='TipoEvento' AND Codigo='CTA_CIERRE'
    )
        INSERT Seguridad.E607CatalogoPropiedad (CodigoObjeto,Codigo)
        VALUES ('TipoEvento','CTA_CIERRE');
END;
COMMIT TRANSACTION;

SET NOCOUNT ON;
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57731, 'Falta confirmar la base destino de reversión E6-07.', 1;
IF OBJECT_ID(N'Seguridad.E607CatalogoPropiedad', N'U') IS NULL
    RETURN;

BEGIN TRANSACTION;
IF EXISTS (
    SELECT 1
    FROM Seguridad.E607CatalogoPropiedad
    WHERE CodigoObjeto='TransaccionesInterfaz' AND Codigo='CTA-CERRAR'
)
BEGIN
    IF EXISTS (
        SELECT 1 FROM Seguridad.SolicitudAprobacion WITH (UPDLOCK, HOLDLOCK)
        WHERE CodigoTransaccion='CTA-CERRAR'
    )
        THROW 57731, 'No se puede retirar CTA-CERRAR: hay solicitudes registradas.', 1;
    IF NOT EXISTS (
        SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
        WHERE CodigoTransaccion='CTA-CERRAR'
          AND Modulo='Cuentas' AND BaseObjetivo='cooperativa'
          AND RolesEjecucion=N'["ADMIN","ASESOR"]'
          AND PermisoAprobacion='cuentas:aprobar' AND EsSensible=1 AND Estado='A'
    )
        THROW 57731, 'CTA-CERRAR cambió desde su creación; se conserva el catálogo.', 1;
    DELETE Seguridad.TransaccionesInterfaz WHERE CodigoTransaccion='CTA-CERRAR';
    DELETE Seguridad.E607CatalogoPropiedad
    WHERE CodigoObjeto='TransaccionesInterfaz' AND Codigo='CTA-CERRAR';
END;

IF EXISTS (
    SELECT 1
    FROM Seguridad.E607CatalogoPropiedad
    WHERE CodigoObjeto='TipoEvento' AND Codigo='CTA_CIERRE'
)
BEGIN
    IF EXISTS (
        SELECT 1 FROM Auditoria.Auditoria WITH (UPDLOCK, HOLDLOCK)
        WHERE CodigoEvento='CTA_CIERRE'
    )
    OR EXISTS (
        SELECT 1 FROM Auditoria.EventoPendiente WITH (UPDLOCK, HOLDLOCK)
        WHERE CodigoEvento='CTA_CIERRE'
    )
        THROW 57731, 'No se puede retirar CTA_CIERRE: hay eventos registrados.', 1;
    IF NOT EXISTS (
        SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK)
        WHERE CodigoEvento='CTA_CIERRE'
          AND Modulo='cuentas' AND Severidad='Sensible' AND EnTransaccion=1
    )
        THROW 57731, 'CTA_CIERRE cambió desde su creación; se conserva el catálogo.', 1;
    DELETE Auditoria.TipoEvento WHERE CodigoEvento='CTA_CIERRE';
    DELETE Seguridad.E607CatalogoPropiedad
    WHERE CodigoObjeto='TipoEvento' AND Codigo='CTA_CIERRE';
END;

IF NOT EXISTS (SELECT 1 FROM Seguridad.E607CatalogoPropiedad)
    DROP TABLE Seguridad.E607CatalogoPropiedad;
COMMIT TRANSACTION;

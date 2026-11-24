/* E3-06 · Configuración de la operación de estado y su evento de auditoría. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57606, 'Falta confirmar la base destino de E3-06.', 1;

BEGIN TRANSACTION;
IF EXISTS (
    SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoTransaccion = 'PRD-ESTADO'
      AND (BaseObjetivo <> 'cooperativa' OR RolesEjecucion <> N'["ADMIN"]'
           OR PermisoAprobacion <> 'productos:aprobar' OR EsSensible <> 1 OR Estado <> 'A')
)
    THROW 57606, 'La operacion PRD-ESTADO existente es incompatible.', 1;

IF EXISTS (
    SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoEvento = 'PRD_ESTADO_CAMBIADO'
      AND (Modulo <> 'productos' OR Severidad <> 'Sensible' OR EnTransaccion <> 1 OR Estado <> 'A')
)
    THROW 57606, 'El evento PRD_ESTADO_CAMBIADO existente es incompatible.', 1;

IF NOT EXISTS (
    SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoTransaccion = 'PRD-ESTADO'
)
    INSERT INTO Seguridad.TransaccionesInterfaz
        (CodigoTransaccion, NombreTransaccion, Modulo, BaseObjetivo, RolesEjecucion, PermisoAprobacion, EsSensible, Estado)
    VALUES ('PRD-ESTADO', N'Cambiar estado de productos', 'Productos', 'cooperativa', N'["ADMIN"]', 'productos:aprobar', 1, 'A');

IF NOT EXISTS (
    SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK)
    WHERE CodigoEvento = 'PRD_ESTADO_CAMBIADO'
)
    INSERT INTO Auditoria.TipoEvento (CodigoEvento, Modulo, Severidad, EnTransaccion)
    VALUES ('PRD_ESTADO_CAMBIADO', 'productos', 'Sensible', 1);
COMMIT TRANSACTION;

/* E5-04: operación CLI-EDITAR de la cola E0-08 y eventos de edición del cliente. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57504, 'Falta confirmar la base destino de E5-04.', 1;

BEGIN TRANSACTION;
IF NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
               WHERE CodigoTransaccion = 'CLI-EDITAR')
    INSERT Seguridad.TransaccionesInterfaz
        (CodigoTransaccion, NombreTransaccion, Modulo, BaseObjetivo, RolesEjecucion, PermisoAprobacion, EsSensible, Estado)
    VALUES ('CLI-EDITAR', N'Cambios sensibles del cliente', 'Clientes', 'cooperativa',
            N'["ADMIN","ASESOR"]', 'clientes:aprobar', 1, 'A');
IF NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WHERE CodigoTransaccion = 'CLI-EDITAR'
               AND BaseObjetivo = 'cooperativa' AND RolesEjecucion = N'["ADMIN","ASESOR"]'
               AND PermisoAprobacion = 'clientes:aprobar' AND EsSensible = 1 AND Estado = 'A')
    THROW 57504, 'La configuración de CLI-EDITAR es incompatible.', 1;

INSERT Auditoria.TipoEvento (CodigoEvento, Modulo, Severidad, EnTransaccion)
SELECT e.CodigoEvento, e.Modulo, e.Severidad, e.EnTransaccion
FROM (VALUES ('CLI_EDITADO', 'clientes', 'Sensible', 0),
             ('CLI_CAMBIO_SENSIBLE', 'clientes', 'Sensible', 1))
    AS e(CodigoEvento, Modulo, Severidad, EnTransaccion)
WHERE NOT EXISTS (SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK)
                  WHERE CodigoEvento = e.CodigoEvento);
COMMIT TRANSACTION;

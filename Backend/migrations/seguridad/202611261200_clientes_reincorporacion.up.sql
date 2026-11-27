/* Reincorporación de un cliente eliminado: pasa por la cola E0-08 y se audita. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57508, 'Falta confirmar la base destino de la reincorporación.', 1;

BEGIN TRANSACTION;
IF NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WITH (UPDLOCK, HOLDLOCK)
               WHERE CodigoTransaccion = 'CLI-REINCORPORAR')
    INSERT Seguridad.TransaccionesInterfaz
        (CodigoTransaccion, NombreTransaccion, Modulo, BaseObjetivo, RolesEjecucion, PermisoAprobacion, EsSensible, Estado)
    VALUES ('CLI-REINCORPORAR', N'Reincorporar un cliente eliminado', 'Clientes', 'cooperativa',
            N'["ADMIN","ASESOR","SUPERVISOR"]', 'clientes:aprobar', 1, 'A');
IF NOT EXISTS (SELECT 1 FROM Seguridad.TransaccionesInterfaz WHERE CodigoTransaccion = 'CLI-REINCORPORAR'
               AND BaseObjetivo = 'cooperativa' AND RolesEjecucion = N'["ADMIN","ASESOR","SUPERVISOR"]'
               AND PermisoAprobacion = 'clientes:aprobar' AND EsSensible = 1 AND Estado = 'A')
    THROW 57508, 'La configuración de CLI-REINCORPORAR es incompatible.', 1;

INSERT Auditoria.TipoEvento (CodigoEvento, Modulo, Severidad, EnTransaccion)
SELECT e.CodigoEvento, e.Modulo, e.Severidad, e.EnTransaccion
FROM (VALUES ('CLI_REINCORPORADO', 'clientes', 'Sensible', 1)) AS e(CodigoEvento, Modulo, Severidad, EnTransaccion)
WHERE NOT EXISTS (SELECT 1 FROM Auditoria.TipoEvento WITH (UPDLOCK, HOLDLOCK)
                  WHERE CodigoEvento = e.CodigoEvento);
COMMIT TRANSACTION;

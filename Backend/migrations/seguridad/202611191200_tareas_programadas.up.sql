/* E0-06 · Tareas programadas: ventana esperada, tareas nuevas y evento del vigilante (SeguridadDB). Repetible. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57206,'Falta confirmar la base destino de la migracion.',1;
IF OBJECT_ID('Sistema.Tarea','U') IS NULL THROW 57206,'Falta Sistema.Tarea (E0-08).',1;
IF OBJECT_ID('Auditoria.TipoEvento','U') IS NULL THROW 57206,'Falta Auditoria.TipoEvento (202611191000).',1;
IF COL_LENGTH('Sistema.Tarea','VentanaEsperadaMin') IS NULL
 ALTER TABLE Sistema.Tarea ADD VentanaEsperadaMin int NULL
  CONSTRAINT CK_Tarea_E006_Ventana CHECK (VentanaEsperadaMin IS NULL OR VentanaEsperadaMin > 0);
GO
SET XACT_ABORT ON;
BEGIN TRANSACTION;
MERGE Sistema.Tarea AS d USING (VALUES
  ('APR_RECUPERACION',     N'Recupera aprobadas y cancela pendientes sin acceso', 'Aprobaciones', 'cada minuto', 1, 10),
  ('APR_RESUMEN_ANTIGUAS', N'Resumen diario sin vencimiento de solicitudes',      'Aprobaciones', 'diaria',      1, 1500),
  ('APR_AUD_RELEVO',       N'Relevo idempotente de auditoria E0-08',              'Aprobaciones', 'cada minuto', 1, 10),
  ('ATM06_RECUPERACION',   N'Recupera cambios de PIN ATM-06 pendientes',          'ATM',          'cada minuto', 1, 10),
  ('SIS_VIGILANTE',        N'Alerta si una tarea no corre dentro de su ventana',  'Sistema',      'cada 5 minutos', 1, NULL)
) AS o(Codigo, Descripcion, Modulo, Programacion, PermiteManual, Ventana) ON d.Codigo = o.Codigo
WHEN MATCHED THEN UPDATE SET VentanaEsperadaMin = o.Ventana
WHEN NOT MATCHED THEN INSERT(Codigo, Descripcion, Modulo, Programacion, PermiteManual, VentanaEsperadaMin)
 VALUES(o.Codigo, o.Descripcion, o.Modulo, o.Programacion, o.PermiteManual, o.Ventana);
MERGE Auditoria.TipoEvento AS d USING (VALUES
  ('SIS_TAREA_SIN_EJECUTAR', 'sistema', 'Seguridad', 0)
) AS o(CodigoEvento, Modulo, Severidad, EnTransaccion) ON d.CodigoEvento = o.CodigoEvento
WHEN NOT MATCHED THEN INSERT(CodigoEvento, Modulo, Severidad, EnTransaccion) VALUES(o.CodigoEvento, o.Modulo, o.Severidad, o.EnTransaccion);
COMMIT TRANSACTION;

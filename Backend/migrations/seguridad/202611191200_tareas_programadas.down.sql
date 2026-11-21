/* Reversión de 202611191200 (solo fuera de producción). */
DELETE FROM Auditoria.TipoEvento WHERE CodigoEvento = 'SIS_TAREA_SIN_EJECUTAR';
DELETE FROM Sistema.Tarea WHERE Codigo IN ('ATM06_RECUPERACION', 'SIS_VIGILANTE')
  AND NOT EXISTS (SELECT 1 FROM Sistema.TareaEjecucion e WHERE e.Codigo = Sistema.Tarea.Codigo);
IF COL_LENGTH('Sistema.Tarea','VentanaEsperadaMin') IS NOT NULL
BEGIN
  ALTER TABLE Sistema.Tarea DROP CONSTRAINT CK_Tarea_E006_Ventana;
  ALTER TABLE Sistema.Tarea DROP COLUMN VentanaEsperadaMin;
END

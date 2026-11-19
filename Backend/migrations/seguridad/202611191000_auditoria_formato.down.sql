/* Reversión de 202611191000_auditoria_formato (solo fuera de producción). Las columnas nuevas se
   eliminan solo si no hay registros del formato nuevo. */
SET XACT_ABORT ON;
DROP TRIGGER IF EXISTS Auditoria.trg_Auditoria_SoloInsercion;
IF NOT EXISTS (SELECT 1 FROM Auditoria.Auditoria WHERE FormatoAnterior = 0)
BEGIN
 DROP INDEX IF EXISTS UX_Auditoria_IdEvento ON Auditoria.Auditoria;
 DROP INDEX IF EXISTS IX_Auditoria_FechaUTC ON Auditoria.Auditoria;
 DROP INDEX IF EXISTS IX_Auditoria_Correlacion ON Auditoria.Auditoria;
 DROP INDEX IF EXISTS IX_Auditoria_Objetivo ON Auditoria.Auditoria;
 ALTER TABLE Auditoria.Auditoria DROP CONSTRAINT IF EXISTS DF_Auditoria_FormatoNuevo;
 ALTER TABLE Auditoria.Auditoria DROP COLUMN IdEvento, CodigoEvento, FechaHoraUTC, IdAgencia, IdSesion, Canal,
  IdCorrelacion, TipoObjetivo, IdObjetivo, Cambios, FormatoAnterior;
END;
DROP TABLE IF EXISTS Auditoria.TipoEvento;

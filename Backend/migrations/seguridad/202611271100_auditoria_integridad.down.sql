/* E8-02 abajo: solo fuera de producción y sin registros archivados. Restaura los disparadores de E0-05 y E0-08.
   El código que llama a Auditoria.usp_RegistrarEvento debe revertirse antes (o el registro de auditoría fallará). */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128),SESSION_CONTEXT(N'migration_database')),N'')<>DB_NAME()
 THROW 57206,'Falta confirmar la base destino de E8-02.',1;
IF EXISTS (SELECT 1 FROM Auditoria.AuditoriaArchivo) OR EXISTS (SELECT 1 FROM Auditoria.EventoDetalleArchivo)
 THROW 57206,'Hay registros archivados: no se revierte el archivo de la bitácora.',1;
BEGIN TRANSACTION;
BEGIN TRY
 DROP TRIGGER IF EXISTS Seguridad.trg_LogTransacciones_Congelada;
 EXEC(N'CREATE OR ALTER TRIGGER Auditoria.trg_Auditoria_SoloInsercion ON Auditoria.Auditoria AFTER UPDATE, DELETE AS
  BEGIN SET NOCOUNT ON; THROW 57201, N''La bitácora de auditoría no se modifica ni se elimina.'', 1; END');
 -- Definición original exacta de E0-08 (su migración la compara al volver a correr)
 DROP TRIGGER IF EXISTS Auditoria.trg_ED_E008_Inmutable;
 EXEC(N'CREATE TRIGGER Auditoria.trg_ED_E008_Inmutable ON Auditoria.EventoDetalle AFTER UPDATE,DELETE AS BEGIN SET NOCOUNT ON; THROW 57201,''El detalle de auditoria es inmutable.'',1; END');
 DROP PROCEDURE IF EXISTS Auditoria.usp_RegistrarEvento;
 DROP VIEW IF EXISTS Auditoria.vw_Bitacora;
 DROP VIEW IF EXISTS Auditoria.vw_EventoDetalle;
 DROP FUNCTION IF EXISTS Auditoria.fn_HashRegistro;
 DROP TABLE IF EXISTS Auditoria.VerificacionIntegridad;
 DROP TABLE IF EXISTS Auditoria.EventoDetalleArchivo;
 DROP TABLE IF EXISTS Auditoria.AuditoriaArchivo;
 DROP INDEX IF EXISTS UX_Auditoria_Secuencia ON Auditoria.Auditoria;
 IF COL_LENGTH('Auditoria.Auditoria','Secuencia') IS NOT NULL
  ALTER TABLE Auditoria.Auditoria DROP COLUMN Secuencia, HashAnterior, Hash;
 DELETE FROM Sistema.Tarea WHERE Codigo IN ('AUD_VERIFICAR_INTEGRIDAD','AUD_ARCHIVAR')
   AND NOT EXISTS (SELECT 1 FROM Sistema.TareaEjecucion e WHERE e.Codigo = Sistema.Tarea.Codigo);
 DELETE FROM Auditoria.TipoEvento WHERE CodigoEvento IN ('AUD_INTEGRIDAD_ROTA','AUD_ARCHIVO')
   AND NOT EXISTS (SELECT 1 FROM Auditoria.Auditoria a WHERE a.CodigoEvento = Auditoria.TipoEvento.CodigoEvento);
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;

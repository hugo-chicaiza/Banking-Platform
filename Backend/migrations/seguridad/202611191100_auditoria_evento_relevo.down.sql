/* Reversión de 202611191100 (solo fuera de producción). */
DELETE FROM Auditoria.TipoEvento WHERE CodigoEvento = 'AUD_RELEVO_ALERTA';

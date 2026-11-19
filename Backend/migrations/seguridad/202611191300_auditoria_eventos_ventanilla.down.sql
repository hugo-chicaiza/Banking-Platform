/* Reversión de 202611191300 (solo fuera de producción). */
DELETE FROM Auditoria.TipoEvento WHERE CodigoEvento IN ('REGISTRAR_DEPOSITO', 'REGISTRAR_RETIRO');

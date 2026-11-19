/* Reversión de 202611191400 (solo fuera de producción). */
DELETE FROM Auditoria.TipoEvento WHERE CodigoEvento IN ('ATM_RETIRO', 'ATM_TRANSFERENCIA', 'ATM_REVERSO', 'ATM_DEPOSITO');

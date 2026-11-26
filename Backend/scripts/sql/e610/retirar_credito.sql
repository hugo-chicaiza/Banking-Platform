/* Corte autorizado por separado. Preconfigurar migration_database y migration_actor_id. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57710, 'Confirme la base destino de E6-10.', 1;
DECLARE @actor int = TRY_CONVERT(int, SESSION_CONTEXT(N'migration_actor_id'));
IF @actor IS NULL OR @actor <= 0
    THROW 57712, 'Indique la identidad auditada para el retiro de crédito.', 1;

BEGIN TRANSACTION;

IF EXISTS (
    SELECT 1
    FROM Tarjeta.Tarjeta t
    JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto = t.IdSubProducto
    WHERE s.CodigoSubProducto = 'TCR001-MC'
      AND t.Estado NOT IN ('Anulada', 'Cancelada', 'Cerrada', 'Vencida')
      AND NOT EXISTS (
         SELECT 1 FROM Tarjeta.TransicionEstado e
         WHERE e.EstadoOrigen = t.Estado AND e.EstadoDestino = 'Anulada'
      )
)
    THROW 57713, 'Hay tarjetas de crédito cuyo estado requiere un procedimiento de anulación autorizado.', 1;

UPDATE ProductosFinancieros.SubProducto
SET Estado = 'I', EstadoSubProducto = 'Suspendido'
WHERE CodigoSubProducto = 'TCR001-MC' AND EstadoSubProducto IN ('Activo', 'Suspendido');

DECLARE @anuladas TABLE (IdTarjeta int, EstadoAnterior varchar(20));
UPDATE t
SET Estado = 'Anulada',
    MotivoEstado = 'PRODUCTO_SUSPENDIDO',
    FechaResolucion = CASE WHEN t.Estado = 'Solicitada'
        THEN CONVERT(datetime2, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time')
        ELSE t.FechaResolucion END
OUTPUT INSERTED.IdTarjeta, DELETED.Estado INTO @anuladas
FROM Tarjeta.Tarjeta t
JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto = t.IdSubProducto
WHERE s.CodigoSubProducto = 'TCR001-MC'
  AND t.Estado NOT IN ('Anulada', 'Cancelada', 'Cerrada', 'Vencida');

INSERT Tarjeta.TarjetaHis (
    IdTarjeta, TipoEvento, EstadoAnterior, EstadoActual, Descripcion, IdCanal, RealizadoPor
)
SELECT IdTarjeta, 'Anulacion', EstadoAnterior, 'Anulada', N'Subproducto de crédito suspendido',
       (SELECT IdCanal FROM Canal.Canal WHERE CodigoCanal = 'VENT'), @actor
FROM @anuladas;

COMMIT;

/* E5-06: el paso Pendiente -> Activo sale del trigger y lo hace el backend cuando
   cliente_habilitado cumple todo (archivos incluidos) y deja historial. El trigger
   conserva la vigencia de la evaluación y el bloqueo por resultado Rechazado. */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57506, 'Falta confirmar la base destino de E5-06.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql N'
CREATE OR ALTER TRIGGER Clientes.trg_RiesgoCliente_Evaluacion
ON Clientes.RiesgoCliente
AFTER INSERT
AS
/* Insertar las evaluaciones con EsVigente = 0: este trigger marca como vigente la más
   reciente de cada cliente y bloquea al cliente si resulta Rechazado. El paso de
   Pendiente a Activo lo decide el backend (E5-06, cliente_habilitado). */
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM inserted) RETURN;

    UPDATE r
    SET EsVigente = CASE WHEN r.IdEvaluacion = u.IdUltima THEN 1 ELSE 0 END
    FROM Clientes.RiesgoCliente r
    JOIN (SELECT c.IdCliente,
                 (SELECT TOP (1) x.IdEvaluacion FROM Clientes.RiesgoCliente x
                  WHERE x.IdCliente = c.IdCliente
                  ORDER BY x.FechaEvaluacion DESC, x.IdEvaluacion DESC) AS IdUltima
          FROM (SELECT DISTINCT IdCliente FROM inserted) c) u ON u.IdCliente = r.IdCliente
    WHERE r.EsVigente <> CASE WHEN r.IdEvaluacion = u.IdUltima THEN 1 ELSE 0 END;

    UPDATE cl
    SET Estado = ''Bloqueado''
    FROM Clientes.Cliente cl
    JOIN Clientes.RiesgoCliente r ON r.IdCliente = cl.IdCliente AND r.EsVigente = 1
    WHERE cl.IdCliente IN (SELECT IdCliente FROM inserted)
      AND r.ResultadoEvaluacion = ''Rechazado''
      AND cl.Estado <> ''Bloqueado'';
END;';
COMMIT TRANSACTION;

/* E5-06 abajo: vuelve el trigger anterior (activa al cliente aprobado sin revisar archivos). */
SET XACT_ABORT ON;
IF COALESCE(CONVERT(nvarchar(128), SESSION_CONTEXT(N'migration_database')), N'') <> DB_NAME()
    THROW 57506, 'Falta confirmar la base destino de E5-06.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql N'
CREATE OR ALTER TRIGGER Clientes.trg_RiesgoCliente_Evaluacion
ON Clientes.RiesgoCliente
AFTER INSERT
AS
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
    SET Estado = CASE WHEN r.ResultadoEvaluacion = ''Rechazado'' THEN ''Bloqueado''
                      WHEN r.ResultadoEvaluacion = ''Aprobado'' AND cl.Estado = ''Pendiente'' THEN ''Activo''
                      ELSE cl.Estado END
    FROM Clientes.Cliente cl
    JOIN Clientes.RiesgoCliente r ON r.IdCliente = cl.IdCliente AND r.EsVigente = 1
    WHERE cl.IdCliente IN (SELECT IdCliente FROM inserted)
      AND cl.Estado <> CASE WHEN r.ResultadoEvaluacion = ''Rechazado'' THEN ''Bloqueado''
                            WHEN r.ResultadoEvaluacion = ''Aprobado'' AND cl.Estado = ''Pendiente'' THEN ''Activo''
                            ELSE cl.Estado END;
END;';
COMMIT TRANSACTION;

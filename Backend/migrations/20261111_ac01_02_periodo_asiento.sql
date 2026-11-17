-- Complementa trg_AsientoContable_Reglas: comprueba INSERT y ambas fechas de UPDATE.
CREATE OR ALTER TRIGGER Contabilidad.trg_AsientoContable_PeriodoAC01
ON Contabilidad.AsientoContable
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    IF EXISTS (
        SELECT 1
        FROM (
            SELECT i.FechaAsiento
            FROM inserted AS i
            LEFT JOIN deleted AS d ON d.IdAsientoContable = i.IdAsientoContable
            WHERE d.IdAsientoContable IS NULL
               OR d.Estado <> 'CONTABILIZADO' OR i.Estado <> 'REVERSADO'
            UNION ALL
            SELECT d.FechaAsiento
            FROM deleted AS d
            LEFT JOIN inserted AS i ON i.IdAsientoContable = d.IdAsientoContable
            WHERE i.IdAsientoContable IS NULL
               OR d.Estado <> 'CONTABILIZADO' OR i.Estado <> 'REVERSADO'
        ) AS fechas
        JOIN Contabilidad.PeriodoContable AS p WITH (HOLDLOCK)
            ON p.Anio = YEAR(fechas.FechaAsiento) AND p.Mes = MONTH(fechas.FechaAsiento)
        WHERE p.Estado = 'CERRADO'
    )
        THROW 56007, N'El mes del asiento está cerrado: registre el ajuste en un período abierto.', 1;

    IF EXISTS (
        SELECT 1
        FROM deleted AS d
        LEFT JOIN inserted AS i ON i.IdAsientoContable = d.IdAsientoContable
        WHERE d.Estado = 'REVERSADO'
          AND (i.IdAsientoContable IS NULL OR EXISTS (
              SELECT d.NumeroAsiento, d.FechaAsiento, d.FechaSistema, d.IdTipoAsiento,
                     d.Origen, d.Concepto, d.TotalDebito, d.TotalCredito, d.Estado,
                     d.IdAsientoReversion, d.IdUsuarioCreacion, d.IdAgencia,
                     d.IdConceptoContable, d.IdFechaContable, d.IdPlantillaAsiento,
                     d.ClaveEventoContable, d.HuellaEventoContable
              EXCEPT
              SELECT i.NumeroAsiento, i.FechaAsiento, i.FechaSistema, i.IdTipoAsiento,
                     i.Origen, i.Concepto, i.TotalDebito, i.TotalCredito, i.Estado,
                     i.IdAsientoReversion, i.IdUsuarioCreacion, i.IdAgencia,
                     i.IdConceptoContable, i.IdFechaContable, i.IdPlantillaAsiento,
                     i.ClaveEventoContable, i.HuellaEventoContable
          ))
    )
        THROW 56004, N'Un asiento REVERSADO no se modifica ni se elimina.', 1;

    IF EXISTS (
        SELECT 1
        FROM deleted AS d
        JOIN inserted AS i ON i.IdAsientoContable = d.IdAsientoContable
        WHERE d.Estado = 'CONTABILIZADO'
          AND EXISTS (
              SELECT d.FechaSistema, d.IdAsientoReversion, d.IdPlantillaAsiento,
                     d.ClaveEventoContable, d.HuellaEventoContable
              EXCEPT
              SELECT i.FechaSistema, i.IdAsientoReversion, i.IdPlantillaAsiento,
                     i.ClaveEventoContable, i.HuellaEventoContable
          )
    )
        THROW 56003, N'Un asiento CONTABILIZADO no permite cambiar su trazabilidad.', 1;

    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN Contabilidad.FechaContable AS f ON f.IdFechaContable = i.IdFechaContable
        WHERE f.Fecha <> i.FechaAsiento
           OR (f.EsDiaContable = 0 AND i.Origen NOT IN ('CIERRE', 'AJUSTE'))
    )
        THROW 56006, N'La fecha y el origen deben corresponder al día contable.', 1;
END;

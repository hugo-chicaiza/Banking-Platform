/* PARA REVISION. VALIDADA EN LOCALDB; NO APLICADA EN AZURE.
   Base objetivo: CooperativaDB.
   Fuente: definicion leida en Azure el 2026-11-09.
   Unico cambio funcional: comparar la entrada como time(7), en vez de time(0).
   time(0) redondea 18:59:59.5000000 a 19:00:00; time(7) conserva la precision.
   Exactamente a las 19:00 sigue pasando al siguiente dia contable.
   El parametro ya debe representar hora de Ecuador continental.
   No cambia tablas, calendario ni transacciones historicas.
   Antes de aplicar: confirmar base, cotejar la definicion vigente y acordar
   la migracion con quien mantiene la DB. Ejecutar luego validar_corte.sql.
*/
ALTER FUNCTION Contabilidad.fn_IdFechaContable (@FechaHora datetime2)
RETURNS int
AS
BEGIN
    DECLARE @d date = CAST(@FechaHora AS date), @corte time(0), @id int;

    SELECT @corte = HoraCorte
    FROM Contabilidad.FechaContable
    WHERE Fecha = @d;

    IF @corte IS NOT NULL AND CAST(@FechaHora AS time(7)) >= @corte
        SET @d = DATEADD(day, 1, @d);

    SELECT TOP (1) @id = IdFechaContable
    FROM Contabilidad.FechaContable
    WHERE Fecha >= @d AND EsDiaContable = 1
    ORDER BY Fecha;

    RETURN @id;
END;

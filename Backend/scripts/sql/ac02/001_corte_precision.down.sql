/* REVERSION VALIDADA EN LOCALDB. NO EJECUTADA EN AZURE.
   Solo para revertir 001_corte_precision.up.sql tras autorizacion.
   Restaura el comportamiento leido en CooperativaDB el 2026-11-09.
   IMPORTANTE: vuelve a introducir el redondeo de medio segundo.
   Cotejar la definicion vigente antes de usar; no sobrescribir cambios ajenos.
   No modifica registros historicos.
*/
ALTER FUNCTION Contabilidad.fn_IdFechaContable (@FechaHora datetime2)
RETURNS int
AS
BEGIN
    DECLARE @d date = CAST(@FechaHora AS date), @corte time(0), @id int;

    SELECT @corte = HoraCorte
    FROM Contabilidad.FechaContable
    WHERE Fecha = @d;

    IF @corte IS NOT NULL AND CAST(@FechaHora AS time(0)) >= @corte
        SET @d = DATEADD(day, 1, @d);

    SELECT TOP (1) @id = IdFechaContable
    FROM Contabilidad.FechaContable
    WHERE Fecha >= @d AND EsDiaContable = 1
    ORDER BY Fecha;

    RETURN @id;
END;

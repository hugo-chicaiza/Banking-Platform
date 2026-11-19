CREATE   FUNCTION Transacciones.fn_CalcularComision
        (@CodigoTipo varchar(30), @IdCanal int, @Monto decimal(18,2), @Fecha date)
    RETURNS TABLE
    AS
    /* TR-04: comisiones parametrizadas para un tipo de transacción en un canal, con su valor
       calculado: Fijo = Valor; Porcentaje = Monto x Valor / 100 dentro de [MontoMinimo, MontoMaximo]. */
    RETURN
        SELECT c.IdComision, c.CodigoComision,
               CAST(CASE WHEN c.TipoCalculo = 'Fijo' THEN c.Valor
                         WHEN @Monto * c.Valor / 100 < c.MontoMinimo THEN c.MontoMinimo
                         WHEN @Monto * c.Valor / 100 > c.MontoMaximo THEN c.MontoMaximo
                         ELSE ROUND(@Monto * c.Valor / 100, 2) END AS decimal(18,2)) AS MontoComision
        FROM Transacciones.ComisionTipoTransaccion p
        JOIN Transacciones.Comisiones c ON c.IdComision = p.IdComision
        WHERE p.CodigoTipoTransaccion = @CodigoTipo AND p.IdCanal = @IdCanal AND p.Estado = 'A' AND c.Estado = 'A'
          AND p.VigenciaDesde <= @Fecha AND (p.VigenciaHasta IS NULL OR p.VigenciaHasta > @Fecha)
          AND c.VigenciaDesde <= @Fecha AND (c.VigenciaHasta IS NULL OR c.VigenciaHasta > @Fecha);
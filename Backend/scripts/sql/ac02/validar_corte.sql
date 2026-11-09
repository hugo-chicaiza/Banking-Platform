/* SOLO LECTURA. Ejecutado como consulta el 2026-11-09, sin aplicar la correccion.
   No crea ni modifica funciones, tablas ni registros.
   Compara la funcion instalada con una expresion equivalente a la propuesta.
   La expresion propuesta es un oraculo de revision, no una implementacion
   alternativa para el backend. Tras una migracion autorizada, ResultadoActual
   debe coincidir con Esperado en todos los casos.
   Las expectativas usan el calendario 2026 verificado el 2026-11-09:
   1-ene feriado; 2-ene habil; 6-nov viernes habil; 7/8-nov fin de semana;
   9/10-nov habiles. Si cambia la semilla, revisar expectativas antes de evaluar.
   Los literales expresan hora de Ecuador; no se usa el reloj del servidor.
*/
;WITH Casos AS (
    SELECT Etiqueta, CONVERT(datetime2(7), InstanteTexto, 126) AS Instante,
           CONVERT(date, EsperadoTexto, 23) AS Esperado
    FROM (VALUES
        (N'Feriado', '2026-01-01T10:00:00.0000000', '2026-01-02'),
        (N'Viernes antes del corte', '2026-11-06T18:59:59.0000000', '2026-11-06'),
        (N'Viernes medio segundo antes', '2026-11-06T18:59:59.5000000', '2026-11-06'),
        (N'Viernes exactamente en corte', '2026-11-06T19:00:00.0000000', '2026-11-09'),
        (N'Viernes despues', '2026-11-06T19:05:00.0000000', '2026-11-09'),
        (N'Sabado', '2026-11-07T10:00:00.0000000', '2026-11-09'),
        (N'Domingo', '2026-11-08T10:00:00.0000000', '2026-11-09'),
        (N'Lunes antes del redondeo', '2026-11-09T18:59:59.4999999', '2026-11-09'),
        (N'Lunes medio segundo antes', '2026-11-09T18:59:59.5000000', '2026-11-09'),
        (N'Lunes ultimo instante previo', '2026-11-09T18:59:59.9999999', '2026-11-09'),
        (N'Lunes exactamente en corte', '2026-11-09T19:00:00.0000000', '2026-11-10'),
        (N'Lunes despues', '2026-11-09T19:00:00.0000001', '2026-11-10'),
        (N'Fuera del calendario', '2099-01-01T10:00:00.0000000', NULL)
    ) AS v(Etiqueta, InstanteTexto, EsperadoTexto)
), Resultados AS (
    SELECT c.*, actual.Fecha AS ResultadoActual, propuesta.Fecha AS ResultadoPropuesto
    FROM Casos c
    LEFT JOIN Contabilidad.FechaContable dia ON dia.Fecha = CAST(c.Instante AS date)
    LEFT JOIN Contabilidad.FechaContable actual
        ON actual.IdFechaContable = Contabilidad.fn_IdFechaContable(c.Instante)
    OUTER APPLY (
        SELECT TOP (1) f.Fecha
        FROM Contabilidad.FechaContable f
        WHERE f.EsDiaContable = 1 AND f.Fecha >=
            CASE WHEN dia.HoraCorte IS NOT NULL
                      AND CAST(c.Instante AS time(7)) >= CAST(dia.HoraCorte AS time(0))
                 THEN DATEADD(day, 1, CAST(c.Instante AS date))
                 ELSE CAST(c.Instante AS date) END
        ORDER BY f.Fecha
    ) propuesta
)
-- Se devuelve el instante como texto para conservar las siete cifras decimales
-- al leerlo con clientes cuyo datetime solo admite microsegundos.
SELECT Etiqueta, CONVERT(varchar(33), Instante, 126) AS Instante,
       Esperado, ResultadoActual, ResultadoPropuesto,
       CASE WHEN ResultadoActual = Esperado
                  OR (ResultadoActual IS NULL AND Esperado IS NULL)
            THEN 'OK' ELSE 'DIFERENCIA' END AS EstadoActual,
       CASE WHEN ResultadoPropuesto = Esperado
                  OR (ResultadoPropuesto IS NULL AND Esperado IS NULL)
            THEN 'OK' ELSE 'DIFERENCIA' END AS EstadoPropuesta
FROM Resultados
ORDER BY Instante;

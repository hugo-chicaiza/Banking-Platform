-- AC-01: las pérdidas de patrimonio 3602 y 3604 son deudoras,
-- sin clasificarlas como cuentas de valuación. Aplicar después de AC-01 02.
CREATE OR ALTER TRIGGER Contabilidad.trg_CuentasContables_PadreNoImputable
ON Contabilidad.CuentasContables
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    /* Una cuenta con hijas no puede ser imputable */
    IF EXISTS (
        SELECT 1
        FROM Contabilidad.CuentasContables p
        WHERE p.EsImputable = 1
          AND EXISTS (
              SELECT 1 FROM Contabilidad.CuentasContables h
              WHERE h.IdCuentaSuperior = p.IdCuentaContable
          )
          AND (p.IdCuentaContable IN (SELECT i.IdCuentaContable FROM inserted i)
               OR p.IdCuentaContable IN (
                   SELECT i.IdCuentaSuperior FROM inserted i
                   WHERE i.IdCuentaSuperior IS NOT NULL
               ))
    )
        THROW 51100, N'Una cuenta contable con cuentas hijas no puede ser imputable: marque la cuenta padre con EsImputable = 0.', 1;

    /* CO-06: el código de la hija empieza con el del padre */
    IF EXISTS (
        SELECT 1
        FROM inserted h
        JOIN Contabilidad.CuentasContables p ON p.IdCuentaContable = h.IdCuentaSuperior
        WHERE NOT (LEN(h.CodigoCuenta) > LEN(p.CodigoCuenta)
                   AND LEFT(h.CodigoCuenta, LEN(p.CodigoCuenta)) = p.CodigoCuenta)
    )
        THROW 56010, N'El código de una cuenta hija debe empezar con el código de su cuenta padre.', 1;

    /* CO-06: naturaleza habitual, salvo valuación y las dos pérdidas del CUC. */
    IF EXISTS (
        SELECT 1
        FROM inserted c
        JOIN Contabilidad.ElementoCUC e ON e.CodigoElemento = c.CodigoElemento
        WHERE e.NaturalezaHabitual IS NOT NULL
          AND c.Naturaleza <> e.NaturalezaHabitual
          AND c.EsCuentaValuacion = 0
          AND NOT (
              e.CodigoElemento = '3'
              AND c.CodigoCuenta IN ('3602', '3604')
              AND c.Naturaleza = 'DEUDORA'
          )
    )
        THROW 56011, N'La naturaleza de la cuenta no coincide con la de su elemento: si es una cuenta de valuación, márquela con EsCuentaValuacion = 1.', 1;
END;

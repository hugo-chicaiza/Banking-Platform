-- Requiere E3-05, que deriva la cuenta de ingreso desde la categoría del servicio.
EXEC(N'CREATE OR ALTER TRIGGER Transacciones.trg_Comisiones_RepTdbCuentaIngreso
ON Transacciones.Comisiones AFTER INSERT, UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM inserted i
        LEFT JOIN Transacciones.CategoriaServicio k ON k.Codigo=i.Categoria
        LEFT JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=k.IdCuentaContable
        WHERE i.CodigoComision=''REP-TDB'' AND i.Estado=''A''
          AND (c.IdCuentaContable IS NULL OR c.Estado<>1 OR c.EsImputable<>1
               OR c.CodigoCuenta NOT LIKE ''5%''
               OR EXISTS (SELECT 1 FROM Contabilidad.CuentasContables h
                          WHERE h.IdCuentaSuperior=c.IdCuentaContable))
    )
        THROW 57872, N''REP-TDB requiere una cuenta de ingreso activa, imputable y de último nivel en su categoría.'', 1;
END;');

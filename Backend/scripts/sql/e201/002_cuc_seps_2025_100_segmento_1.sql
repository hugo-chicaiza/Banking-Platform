/* Delta CUC Segmento 1, Resolución SEPS-IGT-2025-100, anexos 1 y 2.
   Ejecutar tras 001_solo_estructura.sql y antes de instalar el corte 004. */
SET NOCOUNT ON;
SET XACT_ABORT ON;
IF DB_NAME()<>N'CooperativaDB' AND DB_NAME() NOT LIKE N'CooperativaDB_E201_Lab[_]%'
    THROW 56340,N'Base fuera del alcance del delta CUC.',1;
IF @@TRANCOUNT<>0 THROW 56340,N'Ejecute el delta sin transacción externa.',1;
BEGIN TRY
    BEGIN TRANSACTION;
    IF EXISTS (SELECT 1 FROM Contabilidad.CuentasContables WITH (UPDLOCK,HOLDLOCK)
               WHERE CodigoCuenta LIKE '3304%')
        THROW 56341,N'Hay códigos de uso mutualista. Revisar el catálogo sin eliminar cuentas.',1;

    DECLARE @Padre int,@Reservas int;
    SELECT @Padre=p.IdCuentaContable
    FROM Contabilidad.CuentasContables p WITH (UPDLOCK,HOLDLOCK)
    JOIN Contabilidad.CuentasContables g ON g.IdCuentaContable=p.IdCuentaSuperior
    WHERE p.CodigoCuenta='7406' AND g.CodigoCuenta='74'
      AND p.Naturaleza='ACREEDORA' AND p.Estado=1 AND p.EsImputable=0;
    SELECT @Reservas=IdCuentaContable
    FROM Contabilidad.CuentasContables WITH (UPDLOCK,HOLDLOCK)
    WHERE CodigoCuenta='33' AND Naturaleza='ACREEDORA' AND Estado=1 AND EsImputable=0;
    IF @Padre IS NULL OR @Reservas IS NULL OR NOT EXISTS (
        SELECT 1 FROM Contabilidad.CuentasContables
        WHERE CodigoCuenta='3301' AND IdCuentaSuperior=@Reservas
    ) THROW 56342,N'Falta validar la jerarquía regulatoria 33/3301 o 74/7406.',1;

    IF NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables WITH (UPDLOCK,HOLDLOCK)
                   WHERE CodigoCuenta='740640')
        INSERT Contabilidad.CuentasContables
            (CodigoCuenta,NombreCuenta,IdCuentaSuperior,Naturaleza,Estado,Saldo,
             EsImputable,EsCuentaValuacion,EsCatalogoRegulador)
        VALUES ('740640',N'Diferimiento extraordinario de provisiones',@Padre,
                'ACREEDORA',1,0,0,0,1);

    IF NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables
                   WHERE CodigoCuenta='740640' AND IdCuentaSuperior=@Padre
                     AND NombreCuenta=N'Diferimiento extraordinario de provisiones'
                     AND Naturaleza='ACREEDORA' AND Estado=1 AND EsImputable=0
                     AND EsCuentaValuacion=0)
        THROW 56343,N'La subcuenta 740640 existente requiere revisión.',1;

    UPDATE c SET EsCatalogoRegulador=1,Descripcion=d.Descripcion
    FROM Contabilidad.CuentasContables c
    JOIN (VALUES
        ('33',N'Reservas legales, especiales y facultativas. En Segmento 1, el fondo de reserva legal se registra bajo 3301 según la normativa del órgano regulador.'),
        ('7406',N'Deficiencia de provisiones. Incluye diferimientos extraordinarios sujetos a un cronograma aprobado por la SEPS.'),
        ('740640',N'Provisiones sujetas al cronograma de diferimiento extraordinario aprobado por la SEPS.')
    ) d(Codigo,Descripcion) ON d.Codigo=c.CodigoCuenta
    WHERE c.EsCatalogoRegulador=0 OR c.Descripcion IS NULL OR c.Descripcion<>d.Descripcion;

    COMMIT;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK;
    THROW;
END CATCH;

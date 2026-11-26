/* Genera cinco manifiestos E4-03 disjuntos. Por defecto solo consulta.
   Para crear únicamente tipos y conceptos, una sesión DBA autorizada debe
   establecer paquete_contable_catalogo=1 y paquete_contable_base=DB_NAME().
   Establecer paquete_contable_vigencia a una fecha ISO futura de Ecuador.
   Este script no escribe plantillas, solicitudes, aprobaciones ni productos. */
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @vigencia date = TRY_CONVERT(date, SESSION_CONTEXT(N'paquete_contable_vigencia'));
DECLARE @hoy date = CONVERT(date, SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time');
DECLARE @crear bit = COALESCE(TRY_CONVERT(bit, SESSION_CONTEXT(N'paquete_contable_catalogo')), 0);
DECLARE @paquete varchar(30) = CONVERT(varchar(30), SESSION_CONTEXT(N'paquete_contable_paquete'));
IF @paquete IS NOT NULL AND @paquete NOT IN ('BASE','ACTUAL','ARQUEO','AMPLIACION','PRIMA')
    THROW 57889, N'Paquete no reconocido.', 1;
IF @vigencia IS NULL OR @vigencia <= @hoy
    THROW 57890, N'Indique una fecha de vigencia futura en paquete_contable_vigencia.', 1;
IF @@TRANCOUNT <> 0
    THROW 57891, N'Ejecute el paquete en una sesión sin transacciones abiertas.', 1;
IF @crear = 1 AND COALESCE(CONVERT(sysname, SESSION_CONTEXT(N'paquete_contable_base')), N'') <> DB_NAME()
    THROW 57892, N'Confirme explícitamente la base para el alta de catálogos.', 1;

DECLARE @reglas TABLE (
    Familia varchar(50) PRIMARY KEY, Tipo varchar(30), Concepto varchar(30),
    Nombre varchar(100), Paquete varchar(10), CrearTipo bit, CrearConcepto bit
);
INSERT @reglas VALUES
 ('RET_EFECTIVO_CAJA','CAJA_RETIRO','RET_EFECTIVO','Retiro en efectivo en ventanilla','BASE',0,0),
 ('RET_EFECTIVO_ATM','ATM_RETIRO','RET_EFECTIVO_ATM','Retiro en efectivo en ATM','ACTUAL',0,1),
 ('DEV_ATM','DEV_ATM','DEV_ATM','Devolución de efectivo ATM a bóveda','ACTUAL',1,1),
 ('CAJA_FALTANTE','CAJA_FALTANTE','AJUSTE_FALTANTE','Faltante aprobado de ventanilla','BASE',0,0),
 ('CAJA_SOBRANTE','CAJA_SOBRANTE','AJUSTE_SOBRANTE','Sobrante aprobado de ventanilla','BASE',0,0),
 ('ATM_SOBRANTE','ATM_SOBRANTE','AJUSTE_SOBRANTE','Sobrante aprobado de ATM','ACTUAL',1,0),
 ('CUENTAS_TRANSFERENCIA_INTERNA','CUENTAS_TRANSFERENCIA','CUENTAS_TRANSFERENCIA','Transferencia interna de depósitos','ACTUAL',0,1),
 ('CUENTAS_COMISION','CUENTAS_COMISION','CUENTAS_COMISION','Comisión autónoma de cuenta sin impuesto','ACTUAL',0,1),
 ('CUENTAS_INTERES_DEVENGO','CUENTAS_INTERES_DEVENGO','CUENTAS_INTERES_DEVENGO','Devengo de interés ordinario de depósitos','ACTUAL',1,1),
 ('CUENTAS_INTERES_CAPITALIZACION','CUENTAS_INTERES_CAPITALIZACION','CUENTAS_INTERES_CAPITALIZACION','Capitalización de interés sin retención fiscal','ACTUAL',1,1),
 ('CREDITO_PAGO_CUENTA','CREDITO_PAGO','PAGO_CREDITO','Pago desde cuenta de principal e interés devengado','BASE',0,0),
 ('CREDITO_INTERES_DEVENGO','CREDITO_INTERES_DEVENGO','CREDITO_INTERES_DEVENGO','Devengo de interés ordinario de crédito','ACTUAL',1,1),
 ('CREDITO_SEGURO_COBRO_CUENTA','CREDITO_SEGURO_COBRO_CUENTA','CREDITO_SEGURO_COBRO_CUENTA','Prima autónoma de desgravamen desde cuenta','ACTUAL',1,1),
 ('APORTE_CERTIFICADO','APORTE_CERTIFICADO','APORTE_CERTIFICADO','Aporte a certificados recibido en caja','AMPLIACION',1,1),
 ('APORTE_REDENCION_CAJA','APORTE_REDENCION','APORTE_REDENCION','Redención de aporte pagada en caja','AMPLIACION',1,1),
 ('APORTE_REDENCION_AHORRO','APORTE_REDENCION','APORTE_REDENCION','Redención de aporte abonada a ahorro','AMPLIACION',1,1),
 ('RED_COMISION_CAUSADA','RED_COMISION','RED_COMISION_CAUSADA','Comisión causada de red de pagos','AMPLIACION',1,1),
 ('RED_INTERCHANGE_GANADO','RED_COMISION','RED_INTERCHANGE_GANADO','Comisión ganada de red de pagos','AMPLIACION',1,1),
 ('CON_PRIMA_SEGURO_DEPOSITOS','CON_PRIMA_SEGURO_DEPOSITOS','CON_PRIMA_SEGURO_DEPOSITOS','Devengo de prima fija y variable del seguro de depósitos','PRIMA',1,1),
 ('CON_DEPOSITOS_NO_CUBIERTOS_ALTA','CON_DEPOSITOS_NO_CUBIERTOS','CON_DEPOSITOS_NO_CUBIERTOS','Aumento del saldo de captaciones no cubiertas','AMPLIACION',1,1),
 ('CON_DEPOSITOS_NO_CUBIERTOS_BAJA','CON_DEPOSITOS_NO_CUBIERTOS','CON_DEPOSITOS_NO_CUBIERTOS','Disminución del saldo de captaciones no cubiertas','AMPLIACION',1,1),
 ('BOV_001_AJUSTEFALTANTE_E','BOVEDA_FALTANTE','AJUSTE_FALTANTE','Faltante aprobado de bóveda 001','ARQUEO',0,0),
 ('BOV_002_AJUSTEFALTANTE_E','BOVEDA_FALTANTE','AJUSTE_FALTANTE','Faltante aprobado de bóveda 002','ARQUEO',0,0),
 ('BOV_001_AJUSTESOBRANTE_I','BOVEDA_SOBRANTE','AJUSTE_SOBRANTE','Sobrante aprobado de bóveda 001','ARQUEO',1,0),
 ('BOV_002_AJUSTESOBRANTE_I','BOVEDA_SOBRANTE','AJUSTE_SOBRANTE','Sobrante aprobado de bóveda 002','ARQUEO',1,0);
IF @paquete IS NOT NULL
    DELETE FROM @reglas WHERE Paquete<>@paquete;

DECLARE @pares TABLE (
    Familia varchar(50), Orden tinyint, Base varchar(15),
    DebeOrigen varchar(15), Debe varchar(30), HaberOrigen varchar(15), Haber varchar(30),
    PRIMARY KEY (Familia,Orden)
);
INSERT @pares VALUES
 ('RET_EFECTIVO_CAJA',1,'PRINCIPAL','PRODUCTO','CAPITAL','FIJA','11010510'),
 ('RET_EFECTIVO_ATM',1,'PRINCIPAL','PRODUCTO','CAPITAL','FIJA','11010515'),
 ('DEV_ATM',1,'PRINCIPAL','FIJA','11010505','FIJA','11010515'),
 ('CAJA_FALTANTE',1,'DIFERENCIA','FIJA','19902505','FIJA','11010510'),
 ('CAJA_SOBRANTE',1,'DIFERENCIA','FIJA','11010510','FIJA','299005'),
 ('ATM_SOBRANTE',1,'DIFERENCIA','FIJA','11010515','FIJA','299005'),
 ('CUENTAS_TRANSFERENCIA_INTERNA',1,'PRINCIPAL','PRODUCTO','CAPITAL','CONTRAPRODUCTO','CAPITAL'),
 ('CUENTAS_COMISION',1,'COMISION','PRODUCTO','CAPITAL','COMISION',NULL),
 ('CUENTAS_INTERES_DEVENGO',1,'INTERES','PRODUCTO','INTERES_GASTO','PRODUCTO','INTERES_POR_PAGAR'),
 ('CUENTAS_INTERES_CAPITALIZACION',1,'INTERES','PRODUCTO','INTERES_POR_PAGAR','PRODUCTO','CAPITAL'),
 ('CREDITO_PAGO_CUENTA',1,'PRINCIPAL','CONTRAPRODUCTO','CAPITAL','PRODUCTO','CARTERA'),
 ('CREDITO_PAGO_CUENTA',2,'INTERES','CONTRAPRODUCTO','CAPITAL','PRODUCTO','INTERES_POR_COBRAR'),
 ('CREDITO_INTERES_DEVENGO',1,'INTERES','PRODUCTO','INTERES_POR_COBRAR','PRODUCTO','INTERES_GANADO'),
 ('CREDITO_SEGURO_COBRO_CUENTA',1,'SEGURO','CONTRAPRODUCTO','CAPITAL','FIJA','25909005'),
 ('APORTE_CERTIFICADO',1,'PRINCIPAL','FIJA','11010510','PRODUCTO','CAPITAL'),
 ('APORTE_REDENCION_CAJA',1,'PRINCIPAL','PRODUCTO','CAPITAL','FIJA','11010510'),
 ('APORTE_REDENCION_AHORRO',1,'PRINCIPAL','PRODUCTO','CAPITAL','CONTRAPRODUCTO','CAPITAL'),
 ('RED_COMISION_CAUSADA',1,'COMISION','FIJA','4290','FIJA','25909010'),
 ('RED_INTERCHANGE_GANADO',1,'COMISION','FIJA','16909005','FIJA','5290'),
 ('CON_PRIMA_SEGURO_DEPOSITOS',1,'PRIMA_FIJA','FIJA','450420','FIJA','25059015'),
 ('CON_PRIMA_SEGURO_DEPOSITOS',2,'PRIMA_VARIABLE','FIJA','450421','FIJA','25059015'),
 ('CON_DEPOSITOS_NO_CUBIERTOS_ALTA',1,'DIFERENCIA','PRODUCTO','DEPOSITO_NO_CUBIERTO','PRODUCTO','CONTRA_DEPOSITO_NO_CUBIERTO'),
 ('CON_DEPOSITOS_NO_CUBIERTOS_BAJA',1,'DIFERENCIA','PRODUCTO','CONTRA_DEPOSITO_NO_CUBIERTO','PRODUCTO','DEPOSITO_NO_CUBIERTO'),
 ('BOV_001_AJUSTEFALTANTE_E',1,'DIFERENCIA','FIJA','19902505','FIJA','11010505'),
 ('BOV_002_AJUSTEFALTANTE_E',1,'DIFERENCIA','FIJA','19902505','FIJA','11010505'),
 ('BOV_001_AJUSTESOBRANTE_I',1,'DIFERENCIA','FIJA','11010505','FIJA','299005'),
 ('BOV_002_AJUSTESOBRANTE_I',1,'DIFERENCIA','FIJA','11010505','FIJA','299005');

DECLARE @lineas TABLE (
    Familia varchar(50), Orden tinyint, Base varchar(15), Lado varchar(7),
    Origen varchar(15), Referencia varchar(30), PRIMARY KEY(Familia,Orden)
);
INSERT @lineas
SELECT p.Familia, l.Orden, p.Base, l.Lado, l.Origen, l.Referencia
FROM @pares p JOIN @reglas r ON r.Familia=p.Familia CROSS APPLY (VALUES
    (2*p.Orden-1,'DEBITO',p.DebeOrigen,p.Debe),
    (2*p.Orden,'CREDITO',p.HaberOrigen,p.Haber)
) l(Orden,Lado,Origen,Referencia);

IF EXISTS (
    SELECT 1 FROM @lineas l WHERE l.Origen='FIJA'
    AND (SELECT COUNT(*) FROM Contabilidad.CuentasContables c
         WHERE c.CodigoCuenta=l.Referencia AND c.Estado=1 AND c.EsImputable=1
         AND NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables h
                         WHERE h.IdCuentaSuperior=c.IdCuentaContable)) <> 1
)
    THROW 57893, N'El paquete tiene una cuenta fija ausente, ambigua o no imputable.', 1;
IF EXISTS (
    SELECT 1 FROM @lineas l WHERE l.Origen IN ('PRODUCTO','CONTRAPRODUCTO')
    AND NOT EXISTS (SELECT 1 FROM Contabilidad.RolCuentaProducto r
                    WHERE r.CodigoRol=l.Referencia AND r.Estado='A')
)
    THROW 57894, N'El paquete tiene un rol E3-05 ausente o inactivo.', 1;

BEGIN TRY
    BEGIN TRANSACTION;
    IF EXISTS (
        SELECT 1 FROM @reglas r
        WHERE (SELECT COUNT(*) FROM Contabilidad.TiposAsiento t WITH (UPDLOCK,HOLDLOCK)
               WHERE t.Codigo=r.Tipo) > 1
           OR (SELECT COUNT(*) FROM Contabilidad.ConceptoContable c WITH (UPDLOCK,HOLDLOCK)
               WHERE c.CodigoConcepto=r.Concepto) > 1
           OR EXISTS (SELECT 1 FROM Contabilidad.TiposAsiento t WITH (UPDLOCK,HOLDLOCK)
                      WHERE t.Codigo=r.Tipo AND (t.EsManual<>0 OR COALESCE(t.Estado,'')<>'A'))
           OR EXISTS (SELECT 1 FROM Contabilidad.ConceptoContable c WITH (UPDLOCK,HOLDLOCK)
                      WHERE c.CodigoConcepto=r.Concepto AND COALESCE(c.Estado,'')<>'Activo')
           OR (r.CrearTipo=0 AND NOT EXISTS (
               SELECT 1 FROM Contabilidad.TiposAsiento t WITH (UPDLOCK,HOLDLOCK) WHERE t.Codigo=r.Tipo))
           OR (r.CrearConcepto=0 AND NOT EXISTS (
               SELECT 1 FROM Contabilidad.ConceptoContable c WITH (UPDLOCK,HOLDLOCK) WHERE c.CodigoConcepto=r.Concepto))
    ) THROW 57895, N'Catálogo equivalente ausente, duplicado, manual o inactivo.', 1;

    IF @crear = 1
    BEGIN
        INSERT Contabilidad.TiposAsiento (Codigo,Nombre,Descripcion,EsManual,Estado)
        SELECT r.Tipo,r.Tipo,MIN(r.Nombre),0,'A'
        FROM @reglas r WHERE r.CrearTipo=1 AND NOT EXISTS (
            SELECT 1 FROM Contabilidad.TiposAsiento t WITH (UPDLOCK,HOLDLOCK) WHERE t.Codigo=r.Tipo)
        GROUP BY r.Tipo;
        INSERT Contabilidad.ConceptoContable (CodigoConcepto,ConceptoDetalle,Estado)
        SELECT r.Concepto,MIN(r.Nombre),'Activo'
        FROM @reglas r WHERE r.CrearConcepto=1 AND NOT EXISTS (
            SELECT 1 FROM Contabilidad.ConceptoContable c WITH (UPDLOCK,HOLDLOCK) WHERE c.CodigoConcepto=r.Concepto)
        GROUP BY r.Concepto;
    END;

    DECLARE @resultado TABLE (
        Familia varchar(50) PRIMARY KEY, Paquete varchar(10), Estado varchar(40),
        Tipo varchar(30), Concepto varchar(30), IdTipo int, IdConcepto int, Nombre varchar(100)
    );
    INSERT @resultado
    SELECT r.Familia,r.Paquete,
           CASE WHEN EXISTS (SELECT 1 FROM Contabilidad.PlantillaAsiento p
                             WHERE p.CodigoPlantilla=r.Familia) THEN 'FAMILIA_EXISTENTE_REVISAR'
                WHEN r.Paquete='ARQUEO' AND NOT EXISTS (
                    SELECT 1 FROM Organizacion.Agencia a
                    WHERE a.IdAgencia=SUBSTRING(r.Familia,5,3) AND a.Estado='A'
                ) THEN 'AGENCIA_INACTIVA_O_AUSENTE'
                WHEN t.IdTipoAsiento IS NULL OR c.IdConceptoContable IS NULL THEN 'CATALOGO_PENDIENTE'
                ELSE 'MANIFIESTO_GENERABLE' END,
           r.Tipo,r.Concepto,t.IdTipoAsiento,c.IdConceptoContable,r.Nombre
    FROM @reglas r
    LEFT JOIN Contabilidad.TiposAsiento t ON t.Codigo=r.Tipo
    LEFT JOIN Contabilidad.ConceptoContable c ON c.CodigoConcepto=r.Concepto;

    SELECT Familia,Paquete,Estado,Tipo,Concepto,IdTipo,IdConcepto
    FROM @resultado ORDER BY Paquete,Familia;

    -- Cada paquete se genera completo o devuelve NULL. Una familia existente requiere reconciliación.
    SELECT p.Paquete,
           CASE WHEN NOT EXISTS (
               SELECT 1 FROM @resultado x WHERE x.Paquete=p.Paquete AND x.Estado<>'MANIFIESTO_GENERABLE'
           ) THEN (
               SELECT r.IdTipo AS idTipoAsiento,
                      JSON_QUERY((
                          SELECT r.Familia AS codigoPlantilla,r.IdConcepto AS idConceptoContable,
                                 CONVERT(char(10),@vigencia,23) AS vigenciaDesde,r.Nombre AS nombre,
                                 JSON_QUERY((
                                     SELECT l.Lado AS lado,l.Base AS base,l.Origen AS origen,
                                            c.IdCuentaContable AS cuenta,
                                            CASE WHEN l.Origen IN ('PRODUCTO','CONTRAPRODUCTO')
                                                 THEN l.Referencia END AS rol
                                     FROM @lineas l LEFT JOIN Contabilidad.CuentasContables c
                                       ON l.Origen='FIJA' AND c.CodigoCuenta=l.Referencia
                                      AND c.Estado=1 AND c.EsImputable=1
                                      AND NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables h
                                                      WHERE h.IdCuentaSuperior=c.IdCuentaContable)
                                     WHERE l.Familia=r.Familia ORDER BY l.Orden FOR JSON PATH
                                 )) AS lineas
                          FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
                      )) AS borrador
               FROM @resultado r WHERE r.Paquete=p.Paquete ORDER BY r.Familia FOR JSON PATH
           ) END AS ManifiestoJSON
    FROM (SELECT DISTINCT Paquete FROM @resultado) p ORDER BY p.Paquete;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

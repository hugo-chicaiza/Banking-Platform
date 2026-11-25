/* Solo lectura sobre CooperativaDB. Completar fecha y metadatos aprobados.
   @Catalogo: [{"codigo":"CAJA_FALTANTE","idTipo":123,"idConcepto":456}]
   @Exterior: [{"agencia":"001","tipo":"ProvisionExterna","cuenta":"código existente"}]
   Los resultados son insumos para E0-08, sin escrituras directas al catálogo. */
SET NOCOUNT ON;
DECLARE @VigenciaDesde date = NULL;
DECLARE @Catalogo nvarchar(max) = N'[]', @Exterior nvarchar(max) = N'[]';
DECLARE @CuentaSobrantes varchar(30) = '299005'; -- Hoja CUC o auxiliar aprobado de esta rama.
IF @CuentaSobrantes IS NULL OR
   (@CuentaSobrantes <> '299005' AND NOT EXISTS (
       SELECT 1 FROM Contabilidad.CuentasContables h
       JOIN Contabilidad.CuentasContables p ON p.IdCuentaContable=h.IdCuentaSuperior
       WHERE h.CodigoCuenta=@CuentaSobrantes AND p.CodigoCuenta='299005'))
    THROW 57871, 'La cuenta de sobrantes debe pertenecer a la rama 299005.', 1;

DECLARE @Lineas TABLE (
    Codigo varchar(50), Orden int, Lado varchar(7), Base varchar(15),
    Origen varchar(15), Referencia varchar(30) NULL, PRIMARY KEY (Codigo, Orden)
);

INSERT @Lineas VALUES
 ('RET_EFECTIVO_CAJA',1,'DEBITO','PRINCIPAL','PRODUCTO','CAPITAL'),
 ('RET_EFECTIVO_CAJA',2,'CREDITO','PRINCIPAL','FIJA','11010510'),
 ('RET_EFECTIVO_ATM',1,'DEBITO','PRINCIPAL','PRODUCTO','CAPITAL'),
 ('RET_EFECTIVO_ATM',2,'CREDITO','PRINCIPAL','FIJA','11010515'),
 ('DEV_ATM',1,'DEBITO','PRINCIPAL','FIJA','11010505'),
 ('DEV_ATM',2,'CREDITO','PRINCIPAL','FIJA','11010515'),
 ('CUENTAS_TRANSFERENCIA_INTERNA',1,'DEBITO','PRINCIPAL','PRODUCTO','CAPITAL'),
 ('CUENTAS_TRANSFERENCIA_INTERNA',2,'CREDITO','PRINCIPAL','CONTRAPRODUCTO','CAPITAL'),
 ('CUENTAS_COMISION',1,'DEBITO','COMISION','PRODUCTO','CAPITAL'),
 ('CUENTAS_COMISION',2,'CREDITO','COMISION','COMISION',NULL),
 ('CREDITO_DESEMBOLSO_CUENTA',1,'DEBITO','PRINCIPAL','PRODUCTO','CARTERA'),
 ('CREDITO_DESEMBOLSO_CUENTA',2,'CREDITO','PRINCIPAL','CONTRAPRODUCTO','CAPITAL'),
 ('CREDITO_PAGO_CUENTA',1,'DEBITO','PRINCIPAL','CONTRAPRODUCTO','CAPITAL'),
 ('CREDITO_PAGO_CUENTA',2,'CREDITO','PRINCIPAL','PRODUCTO','CARTERA'),
 ('CREDITO_PAGO_CUENTA',3,'DEBITO','INTERES','CONTRAPRODUCTO','CAPITAL'),
 ('CREDITO_PAGO_CUENTA',4,'CREDITO','INTERES','PRODUCTO','INTERES_POR_COBRAR'),
 ('CUENTAS_INTERES_DEVENGO',1,'DEBITO','INTERES','PRODUCTO','INTERES_GASTO'),
 ('CUENTAS_INTERES_DEVENGO',2,'CREDITO','INTERES','PRODUCTO','INTERES_POR_PAGAR'),
 ('CUENTAS_INTERES_CAPITALIZACION',1,'DEBITO','INTERES','PRODUCTO','INTERES_POR_PAGAR'),
 ('CUENTAS_INTERES_CAPITALIZACION',2,'CREDITO','INTERES','PRODUCTO','CAPITAL'),
 ('CREDITO_INTERES_DEVENGO',1,'DEBITO','INTERES','PRODUCTO','INTERES_POR_COBRAR'),
 ('CREDITO_INTERES_DEVENGO',2,'CREDITO','INTERES','PRODUCTO','INTERES_GANADO'),
 ('CUENTAS_RETENCION',1,'DEBITO','PRINCIPAL','PRODUCTO','CAPITAL'),
 ('CUENTAS_RETENCION',2,'CREDITO','PRINCIPAL','PRODUCTO','RESTRINGIDO'),
 ('CUENTAS_LIBERACION',1,'DEBITO','PRINCIPAL','PRODUCTO','RESTRINGIDO'),
 ('CUENTAS_LIBERACION',2,'CREDITO','PRINCIPAL','PRODUCTO','CAPITAL'),
 ('CREDITO_SEGURO_COBRO_CUENTA',1,'DEBITO','SEGURO','CONTRAPRODUCTO','CAPITAL'),
 ('CREDITO_SEGURO_COBRO_CUENTA',2,'CREDITO','SEGURO','FIJA','25909005');

INSERT @Lineas
SELECT c.Modulo + '_' + d.Evento, l.Orden, l.Lado, 'DIFERENCIA', 'FIJA', l.Cuenta
FROM (VALUES ('CAJA','11010510'), ('ATM','11010515')) c(Modulo,Efectivo)
CROSS JOIN (VALUES ('FALTANTE','19902505'),('SOBRANTE',@CuentaSobrantes)) d(Evento,Diferencia)
CROSS APPLY (VALUES (1,'DEBITO',CASE WHEN d.Evento='FALTANTE' THEN d.Diferencia ELSE c.Efectivo END),
                    (2,'CREDITO',CASE WHEN d.Evento='FALTANTE' THEN c.Efectivo ELSE d.Diferencia END)) l(Orden,Lado,Cuenta);

-- Cuentas exactas, sin sustituir hojas por agrupadores ni elegir una tarifa.
DECLARE @Cuentas TABLE (Codigo varchar(30) PRIMARY KEY, IdCuenta int, Coincidencias int);
INSERT @Cuentas
SELECT c.CodigoCuenta, MIN(c.IdCuentaContable), COUNT(*)
FROM Contabilidad.CuentasContables c
WHERE c.Estado=1 AND c.EsImputable=1 AND NOT EXISTS (
    SELECT 1 FROM Contabilidad.CuentasContables h WHERE h.IdCuentaSuperior=c.IdCuentaContable
)
GROUP BY c.CodigoCuenta;

DECLARE @Catalogos TABLE (Codigo varchar(50) PRIMARY KEY, IdTipo int, IdConcepto int);
INSERT @Catalogos
SELECT Codigo, IdTipo, IdConcepto
FROM OPENJSON(@Catalogo) WITH (Codigo varchar(50) '$.codigo', IdTipo int '$.idTipo', IdConcepto int '$.idConcepto');

-- Cotejar detalles de familias existentes antes de decidir si necesitan otra versión.
SELECT l.Codigo, l.Orden, l.Lado, l.Base, l.Origen, l.Referencia,
       c.IdCuenta, p.IdPlantillaAsiento, p.Version, p.Estado, p.VigenciaDesde,
       d.TipoMovimiento AS LadoExistente, d.ComponenteImporte AS BaseExistente,
       d.OrigenCuenta AS OrigenExistente, d.CodigoRol AS RolExistente, d.IdCuentaContable AS CuentaExistente,
       CASE WHEN l.Origen='FIJA' AND c.IdCuenta IS NULL THEN 'CUENTA_HOJA_REQUERIDA'
            WHEN l.Origen IN ('PRODUCTO','CONTRAPRODUCTO') AND r.CodigoRol IS NULL THEN 'ROL_ACTIVO_REQUERIDO'
            WHEN l.Origen='COMISION' THEN 'RESOLVER_TARIFA_APLICADA'
            ELSE 'DEFINIDA' END AS EstadoLinea
FROM @Lineas l
LEFT JOIN @Cuentas c ON l.Origen='FIJA' AND c.Codigo=l.Referencia AND c.Coincidencias=1
LEFT JOIN Contabilidad.RolCuentaProducto r ON r.CodigoRol=l.Referencia AND r.Estado='A'
LEFT JOIN Contabilidad.PlantillaAsiento p ON p.CodigoPlantilla=l.Codigo
LEFT JOIN Contabilidad.PlantillaAsientoDetalle d ON d.IdPlantillaAsiento=p.IdPlantillaAsiento AND d.Orden=l.Orden
ORDER BY l.Codigo,p.Version,l.Orden;

;WITH Familias AS (
    SELECT DISTINCT Codigo FROM @Lineas
), Evaluacion AS (
    SELECT f.Codigo, t.IdTipoAsiento, co.IdConceptoContable,
           CASE
             WHEN EXISTS (SELECT 1 FROM Contabilidad.PlantillaAsiento p WHERE p.CodigoPlantilla=f.Codigo)
                 THEN 'FAMILIA_EXISTENTE_REVISAR_HISTORIAL'
             WHEN EXISTS (SELECT 1 FROM @Lineas l WHERE l.Codigo=f.Codigo AND l.Origen='FIJA'
                          AND NOT EXISTS (SELECT 1 FROM @Cuentas c WHERE c.Codigo=l.Referencia AND c.Coincidencias=1))
                 THEN 'CUENTA_HOJA_REQUERIDA'
             WHEN EXISTS (SELECT 1 FROM @Lineas l WHERE l.Codigo=f.Codigo AND l.Origen IN ('PRODUCTO','CONTRAPRODUCTO')
                          AND NOT EXISTS (SELECT 1 FROM Contabilidad.RolCuentaProducto r
                                          WHERE r.CodigoRol=l.Referencia AND r.Estado='A'))
                 THEN 'ROL_ACTIVO_REQUERIDO'
             WHEN t.IdTipoAsiento IS NULL OR co.IdConceptoContable IS NULL
                 THEN 'SELECCIONAR_TIPO_Y_CONCEPTO'
             WHEN @VigenciaDesde IS NULL THEN 'INDICAR_FECHA_PROPUESTA'
             ELSE 'LISTA_PARA_SOLICITUD' END AS Estado
    FROM Familias f LEFT JOIN @Catalogos m ON m.Codigo=f.Codigo
    LEFT JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento=m.IdTipo AND t.EsManual=0 AND t.Estado='A'
    LEFT JOIN Contabilidad.ConceptoContable co ON co.IdConceptoContable=m.IdConcepto AND co.Estado='Activo'
)
SELECT e.Codigo, e.Estado, e.IdTipoAsiento,
       CASE WHEN e.Estado='LISTA_PARA_SOLICITUD' THEN (
           SELECT e.Codigo AS codigoPlantilla, e.Codigo AS nombre, @VigenciaDesde AS vigenciaDesde,
                  e.IdConceptoContable AS idConceptoContable,
                  JSON_QUERY((SELECT l.Lado AS lado, l.Base AS base, l.Origen AS origen,
                                     c.IdCuenta AS cuenta,
                                     CASE WHEN l.Origen IN ('PRODUCTO','CONTRAPRODUCTO') THEN l.Referencia END AS rol
                              FROM @Lineas l
                              LEFT JOIN @Cuentas c ON l.Origen='FIJA' AND c.Codigo=l.Referencia AND c.Coincidencias=1
                              WHERE l.Codigo=e.Codigo ORDER BY l.Orden FOR JSON PATH)) AS lineas
           FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
       ) END AS BorradorE403
FROM Evaluacion e ORDER BY e.Codigo;

-- Mapa de configuración BOV por agencia. Revisar las diferencias en la cola antes del corte.
DECLARE @Contrapartidas TABLE (Agencia char(3), Tipo varchar(30), Cuenta varchar(30), PRIMARY KEY(Agencia,Tipo));
INSERT @Contrapartidas
SELECT Agencia, Tipo, Cuenta
FROM OPENJSON(@Exterior) WITH (Agencia char(3) '$.agencia', Tipo varchar(30) '$.tipo', Cuenta varchar(30) '$.cuenta');

SELECT a.IdAgencia, e.Tipo, e.Naturaleza, reglas.Debe, reglas.Haber,
       d.IdCuenta AS IdDebePropuesto, h.IdCuenta AS IdHaberPropuesto,
       pd.CodigoCuenta AS DebeActual, ph.CodigoCuenta AS HaberActual, p.IdTipoAsiento,
       identidad.Codigo AS CodigoPropuesto, t.IdTipoAsiento AS IdTipoPropuesto,
       co.IdConceptoContable AS IdConceptoPropuesto,
       CASE WHEN reglas.Debe IS NULL OR reglas.Haber IS NULL THEN 'CONTRAPARTIDA_EXTERNA_REQUERIDA'
            WHEN reglas.Debe=reglas.Haber THEN 'CONTRAPARTIDA_IGUAL_A_EFECTIVO'
            WHEN d.IdCuenta IS NULL OR h.IdCuenta IS NULL THEN 'CUENTA_HOJA_REQUERIDA'
            WHEN d.IdCuenta=p.IdCuentaDebito AND h.IdCuenta=p.IdCuentaCredito THEN 'CUENTAS_COINCIDEN'
            WHEN t.IdTipoAsiento IS NULL OR co.IdConceptoContable IS NULL THEN 'SELECCIONAR_TIPO_Y_CONCEPTO'
            ELSE 'REVISAR_Y_APROBAR_REGLA_POR_AGENCIA' END AS Estado,
       CASE WHEN d.IdCuenta IS NOT NULL AND h.IdCuenta IS NOT NULL AND d.IdCuenta<>h.IdCuenta
            AND t.IdTipoAsiento IS NOT NULL AND co.IdConceptoContable IS NOT NULL AND @VigenciaDesde IS NOT NULL
            THEN (SELECT a.IdAgencia AS agencia, e.Tipo AS operacion, e.Naturaleza AS naturaleza,
                         identidad.Codigo AS codigoPlantilla, t.IdTipoAsiento AS idTipoAsiento,
                         co.IdConceptoContable AS idConceptoContable, @VigenciaDesde AS vigenciaDesde,
                         JSON_QUERY((SELECT l.Lado AS lado, l.Cuenta AS cuenta, 'FIJA' AS origen,
                                            CASE WHEN e.Tipo IN ('AjusteFaltante','AjusteSobrante')
                                                 THEN 'DIFERENCIA' ELSE 'PRINCIPAL' END AS base
                                     FROM (VALUES (1,'DEBITO',d.IdCuenta),(2,'CREDITO',h.IdCuenta)) l(Orden,Lado,Cuenta)
                                     ORDER BY l.Orden FOR JSON PATH)) AS lineas
                  FOR JSON PATH, WITHOUT_ARRAY_WRAPPER) END AS BorradorVinculoVersionado
FROM (SELECT DISTINCT IdAgencia FROM Boveda.Boveda WHERE Estado='A') a
CROSS JOIN (VALUES ('AjusteFaltante','E','19902505'),('AjusteSobrante','I',@CuentaSobrantes),
                   ('ProvisionExterna','I',NULL),('EnvioExcedente','E',NULL),
                   ('Traslado','E','19080505'),('Traslado','I','19080505')) e(Tipo,Naturaleza,Contrapartida)
LEFT JOIN @Contrapartidas x ON x.Agencia=a.IdAgencia AND x.Tipo=e.Tipo
    AND e.Tipo IN ('ProvisionExterna','EnvioExcedente')
CROSS APPLY (VALUES (CASE WHEN e.Naturaleza='I' THEN '11010505' ELSE COALESCE(e.Contrapartida,x.Cuenta) END,
                     CASE WHEN e.Naturaleza='E' THEN '11010505' ELSE COALESCE(e.Contrapartida,x.Cuenta) END)) reglas(Debe,Haber)
CROSS APPLY (VALUES (CONCAT('BOV_',RTRIM(a.IdAgencia),'_',UPPER(e.Tipo),'_',e.Naturaleza))) identidad(Codigo)
LEFT JOIN @Cuentas d ON d.Codigo=reglas.Debe AND d.Coincidencias=1
    AND (x.Cuenta IS NULL OR x.Cuenta IN ('110305','110310','110315','110320'))
LEFT JOIN @Cuentas h ON h.Codigo=reglas.Haber AND h.Coincidencias=1
    AND (x.Cuenta IS NULL OR x.Cuenta IN ('110305','110310','110315','110320'))
LEFT JOIN Contabilidad.PlantillaBoveda p ON p.IdAgencia=a.IdAgencia
    AND p.TipoMovimiento=e.Tipo AND p.Naturaleza=e.Naturaleza
LEFT JOIN Contabilidad.CuentasContables pd ON pd.IdCuentaContable=p.IdCuentaDebito
LEFT JOIN Contabilidad.CuentasContables ph ON ph.IdCuentaContable=p.IdCuentaCredito
LEFT JOIN @Catalogos m ON m.Codigo=identidad.Codigo
LEFT JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento=COALESCE(m.IdTipo,p.IdTipoAsiento)
    AND t.EsManual=0 AND t.Estado='A'
LEFT JOIN Contabilidad.ConceptoContable co ON co.IdConceptoContable=m.IdConcepto AND co.Estado='Activo'
ORDER BY a.IdAgencia,e.Tipo,e.Naturaleza;

/* Prerrequisitos de E4-03. Revisión DBA antes de ejecutar.
   Crea exclusivamente metadatos inexistentes. Las reglas pasan por E0-08.
   Use códigos equivalentes ya aprobados en @Reusar si el catálogo los tiene. */
SET XACT_ABORT ON;
SET NOCOUNT ON;
DECLARE @Reusar nvarchar(max) = N'[]'; -- [{"familia":"CAJA_FALTANTE","tipo":"...","concepto":"..."}]
DECLARE @Familias TABLE (Familia varchar(30) PRIMARY KEY, Nombre nvarchar(80));
INSERT @Familias VALUES
 ('CAJA_FALTANTE',N'Faltante de ventanilla'), ('CAJA_SOBRANTE',N'Sobrante de ventanilla'),
 ('ATM_FALTANTE',N'Faltante de ATM'), ('ATM_SOBRANTE',N'Sobrante de ATM'),
 ('BOV_AJUSTEFALTANTE_E',N'Faltante de bóveda'), ('BOV_AJUSTESOBRANTE_I',N'Sobrante de bóveda'),
 ('BOV_PROVISIONEXTERNA_I',N'Provisión externa de efectivo'),
 ('BOV_ENVIOEXCEDENTE_E',N'Envío de excedente de efectivo'),
 ('BOV_TRASLADO_E',N'Despacho de efectivo en tránsito'), ('BOV_TRASLADO_I',N'Recepción de efectivo en tránsito'),
 ('RET_EFECTIVO_CAJA',N'Retiro de ventanilla'), ('RET_EFECTIVO_ATM',N'Retiro de ATM'),
 ('DEV_ATM',N'Devolución de ATM a bóveda'),
 ('CUENTAS_TRANSFERENCIA_INTERNA',N'Transferencia interna'), ('CUENTAS_COMISION',N'Comisión de cuenta'),
 ('CREDITO_DESEMBOLSO_CUENTA',N'Desembolso de crédito a cuenta'),
 ('CREDITO_PAGO_CUENTA',N'Pago de crédito desde cuenta'),
 ('CUENTAS_INTERES_DEVENGO',N'Devengo de interés de depósitos'),
 ('CUENTAS_INTERES_CAPITALIZACION',N'Capitalización de interés de depósitos'),
 ('CREDITO_INTERES_DEVENGO',N'Devengo de interés de crédito'),
 ('CREDITO_SEGURO_COBRO_CUENTA',N'Cargo autónomo de prima de desgravamen');

DECLARE @Mapa TABLE (Familia varchar(30) PRIMARY KEY, Tipo varchar(30), Concepto varchar(30));
INSERT @Mapa
SELECT f.Familia,COALESCE(j.Tipo,f.Familia),COALESCE(j.Concepto,f.Familia)
FROM @Familias f
LEFT JOIN OPENJSON(@Reusar) WITH (Familia varchar(30) '$.familia', Tipo varchar(30) '$.tipo',
                                 Concepto varchar(30) '$.concepto') j ON j.Familia=f.Familia;

BEGIN TRY
    BEGIN TRAN;
    IF EXISTS (
        SELECT 1 FROM @Mapa m
        LEFT JOIN Contabilidad.TiposAsiento t WITH(UPDLOCK,HOLDLOCK) ON t.Codigo=m.Tipo
        LEFT JOIN Contabilidad.ConceptoContable c WITH(UPDLOCK,HOLDLOCK) ON c.CodigoConcepto=m.Concepto
        WHERE (t.IdTipoAsiento IS NOT NULL AND (t.Estado<>'A' OR t.EsManual<>0))
           OR (c.IdConceptoContable IS NOT NULL AND c.Estado<>'Activo')
           OR (m.Tipo<>m.Familia AND t.IdTipoAsiento IS NULL)
           OR (m.Concepto<>m.Familia AND c.IdConceptoContable IS NULL)
    ) THROW 57873, N'Metadatos existentes incompatibles o códigos de reutilización no encontrados.', 1;

    INSERT Contabilidad.TiposAsiento (Codigo,Nombre,Descripcion,EsManual,Estado)
    SELECT m.Tipo,f.Nombre,f.Nombre,0,'A' FROM @Mapa m JOIN @Familias f ON f.Familia=m.Familia
    WHERE m.Tipo=m.Familia AND NOT EXISTS (
        SELECT 1 FROM Contabilidad.TiposAsiento t WITH(UPDLOCK,HOLDLOCK) WHERE t.Codigo=m.Tipo);
    INSERT Contabilidad.ConceptoContable (CodigoConcepto,ConceptoDetalle,Estado)
    SELECT m.Concepto,f.Nombre,'Activo' FROM @Mapa m JOIN @Familias f ON f.Familia=m.Familia
    WHERE m.Concepto=m.Familia AND NOT EXISTS (
        SELECT 1 FROM Contabilidad.ConceptoContable c WITH(UPDLOCK,HOLDLOCK) WHERE c.CodigoConcepto=m.Concepto);
    IF EXISTS (SELECT 1 FROM @Mapa m WHERE (SELECT COUNT(*) FROM Contabilidad.ConceptoContable c
                    WHERE c.CodigoConcepto=m.Concepto)<>1)
        THROW 57874, N'Concepto contable ambiguo.', 1;
    COMMIT;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK;
    THROW;
END CATCH;

-- Copiar el JSON de salida a @Catalogo en preparar_cobertura_e403.sql.
SELECT (
    SELECT CASE WHEN m.Familia LIKE 'BOV[_]%' THEN CONCAT('BOV_',RTRIM(a.IdAgencia),'_',SUBSTRING(m.Familia,5,30))
                ELSE m.Familia END AS codigo,
           COALESCE(pb.IdTipoAsiento,t.IdTipoAsiento) AS idTipo, c.IdConceptoContable AS idConcepto
    FROM @Mapa m
    JOIN Contabilidad.TiposAsiento t ON t.Codigo=m.Tipo
    JOIN Contabilidad.ConceptoContable c ON c.CodigoConcepto=m.Concepto
    OUTER APPLY (SELECT DISTINCT b.IdAgencia FROM Boveda.Boveda b WHERE b.Estado='A' AND m.Familia LIKE 'BOV[_]%') a
    LEFT JOIN Contabilidad.PlantillaBoveda pb ON pb.IdAgencia=a.IdAgencia
      AND CONCAT('BOV_',UPPER(pb.TipoMovimiento),'_',pb.Naturaleza)=m.Familia
    WHERE m.Familia NOT LIKE 'BOV[_]%' OR a.IdAgencia IS NOT NULL
    FOR JSON PATH
) AS CatalogoJSON;

# ATM_FALTANTE — configuración aprobada en Azure Dev

La propuesta de E10-03 #102 usa el auxiliar `19902515` bajo `199025` (Faltantes de caja, CUC segmento 1). El auxiliar separa los faltantes ATM de Caja y Bóveda. La conciliación del efectivo compara `11010515` con las gavetas. La conciliación del auxiliar de faltantes exige el detalle de cada cuadre y su regularización.

| Familia | Tipo existente en Dev | Concepto existente en Dev | Debe | Haber | Base |
| --- | --- | --- | --- | --- | --- |
| `ATM_FALTANTE` | `ATM_FALTANTE` (17) | `AJUSTE_FALTANTE` (9) | `19902515` | `11010515` | `DIFERENCIA` |

## Validación del catálogo y SoloAutomatica

En CooperativaDB Dev, `199025` (ID 799) es deudora, activa, reguladora y no imputable bajo `1990`. Su hija `19902505` (ID 1194) es una hoja deudora, activa e imputable, con `EsCatalogoRegulador=0`, `EsCuentaValuacion=0` y `SoloAutomatica=0`. `19902515` cumple el formato numérico de ocho dígitos y se propone con esos mismos atributos y saldo inicial cero. El CUC define `199025`; #102 identifica el auxiliar operativo.

Se mantiene `SoloAutomatica=0` en el auxiliar de faltantes. Sigue la política del auxiliar hermano y deja disponible la regularización contable autorizada del saldo. El evento operativo siempre usa el tipo automático 17. `11010515` conserva `SoloAutomatica=1`; el disparador 56312 bloquea movimientos manuales ordinarios contra ese efectivo, incluida una corrección manual que intentara tocar ambas cuentas. Cualquier ajuste autorizado debe seguir su flujo vigente.

## Evidencia en Azure Dev

Configuración contable completa. El auxiliar `19902515` (ID 1224) está activo e imputable, con saldo inicial 0,00. Swagger simuló un faltante de 50,00 con débito a 1224 y crédito a 1198 (`11010515)). La solicitud 45 creó la plantilla v1, ID 37, activa y seleccionable desde el 30/11/2026. Creó el usuario 37 y aprobó el usuario 38 el 27/11/2026 a las 06:33:32.6497861, según SQL. La selección por vigencia se verificó en SQL.

El [manifiesto Dev registrado](../scripts/sql/manifiestos_e403/atm_faltante_dev.json) conserva los IDs y las líneas de esa configuración como evidencia.

## Procedimiento de alta conservado para auditoría

1. Ejecutar la [consulta previa de solo lectura](../scripts/sql/verificar_atm_faltante_pre.sql) desde CooperativaDB Dev. Comprobar el padre, la cuenta de efectivo, el tipo 17 activo y automático, el concepto 9 activo y la ausencia de familia. Si aparece el auxiliar con historia previa, revisar los movimientos antes de avanzar.
2. En SSMS, conectado expresamente a Azure Dev y con CooperativaDB seleccionada, ejecutar el siguiente encabezado y todo el contenido de la [migración versionada completa](../migrations/cooperativa/202611271200_contabilidad_atm_faltantes.up.sql) en la misma sesión, sin transacción externa. La migración conserva el ID en reintentos, aborta ante usos incompatibles y revierte ante error. La baja requiere revisión contable explícita por tratarse de un código que puede existir antes de la migración o adquirir referencias.
3. Ejecutar la [consulta posterior de solo lectura](../scripts/sql/verificar_atm_faltante_post.sql). Para el alta inicial debe devolver `LISTO_PARA_GENERAR`, cero hijas y movimientos, saldo cero y ninguna fila de plantilla.
4. Fijar `atm_faltante_vigencia` en la sesión a una fecha hábil posterior a la efectiva que deje margen para la segunda aprobación. Ejecutar el [generador de solo lectura](../scripts/sql/preparar_atm_faltante.sql) en esa sesión. Resuelve ambos IDs contables por código y produce `ManifiestoJSON`, `SimulacionSwaggerJSON` y `RegistroSwaggerJSON`. Se usa el ID real que reciba `19902515` en Dev.
5. Pegar `SimulacionSwaggerJSON` en `POST /api/v1/contabilidad/plantillas/simulaciones` y verificar dos líneas por 50,00. Cuando se autorice el registro, pegar `RegistroSwaggerJSON` en `POST /api/v1/contabilidad/tipos-asiento/17/plantillas`. Incluye `soloPrimeraVersion: true`. Guardar los IDs y aprobar con una sesión independiente.

```sql
IF DB_NAME() <> N'CooperativaDB'
    THROW 57939, N'Seleccione CooperativaDB en Azure Dev.', 1;
EXEC sys.sp_set_session_context @key = N'migration_database', @value = N'CooperativaDB';
-- Ejecutar ahora la migración completa en esta misma sesión.
```

## Ensayo local

La prueba genera el manifiesto, valida el borrador con el modelo de E4-03 y simula 50,00. Sobre una proyección SQL Server de E4-01, la contabilización debe seleccionar la versión instalada solo para el ensayo, usar numeración nativa, dejar el estado CONTABILIZADO y cuadrar 50,00 por lado. El asiento sube `19902515` en 50,00 y baja `11010515` en 50,00. Comprueba también los ascendientes, la igualdad de ID al repetir, el rechazo de la misma clave con otro importe y el rollback del asiento, las líneas, los saldos y el registro de negocio de prueba.

## Integración ATM pendiente

ATM debe emitir `ATM_CUADRE` al aprobar un faltante positivo. Debe persistir el identificador del cuadre, la terminal, la agencia y el vínculo al asiento. El ajuste del efectivo y el asiento deben confirmarse en la misma transacción y revertirse juntos si falla la contabilización. La clave de evento debe ser estable por cuadre y los reintentos deben devolver el resultado original sin duplicar el ajuste ni el asiento. Estos controles siguen pendientes de prueba integral con el productor real. [E10-03 #102](https://github.com/hugo-chicaiza/Banking-Platform/issues/102)

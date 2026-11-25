# Registro y aprobación de las reglas de E4-03

## Inventario

Las siete familias confirmadas en CooperativaDB son `CAJA_DEPOSITO`, `DEV_CAJA`, `DOT_CAJA`, `DOT_ATM`, `CUENTAS_LIBERACION`, `CUENTAS_RECLASIFICACION` y `CUENTAS_RETENCION`. El diagnóstico compartido confirma que estaban habilitadas. Para ver su número de versión e historial exactos, ejecutar el siguiente inventario en SSMS. La semilla del repositorio define la versión 1 de las primeras cuatro. Las cuatro reglas de traslado existentes en `PlantillaBoveda` carecen de número de versión.

```sql
SELECT CodigoPlantilla, Version, Estado, VigenciaDesde, VigenciaHasta, IdPlantillaAsiento
FROM Contabilidad.PlantillaAsiento
ORDER BY CodigoPlantilla, Version;
```

El registro inicial puede solicitar **27 familias nuevas en versión 1** para las agencias 001 y 002, si no existen en el ambiente al preparar el manifiesto.

- **15 generales:** `CAJA_FALTANTE`, `CAJA_SOBRANTE`, `ATM_FALTANTE`, `ATM_SOBRANTE`, `RET_EFECTIVO_CAJA`, `RET_EFECTIVO_ATM`, `DEV_ATM`, `CUENTAS_TRANSFERENCIA_INTERNA`, `CUENTAS_COMISION`, `CUENTAS_INTERES_DEVENGO`, `CUENTAS_INTERES_CAPITALIZACION`, `CREDITO_DESEMBOLSO_CUENTA`, `CREDITO_PAGO_CUENTA`, `CREDITO_INTERES_DEVENGO` y `CREDITO_SEGURO_COBRO_CUENTA`.
- **Seis de agencia 001:** `BOV_001_AJUSTEFALTANTE_E`, `BOV_001_AJUSTESOBRANTE_I`, `BOV_001_PROVISIONEXTERNA_I`, `BOV_001_ENVIOEXCEDENTE_E`, `BOV_001_TRASLADO_E` y `BOV_001_TRASLADO_I`.
- **Seis de agencia 002:** `BOV_002_AJUSTEFALTANTE_E`, `BOV_002_AJUSTESOBRANTE_I`, `BOV_002_PROVISIONEXTERNA_I`, `BOV_002_ENVIOEXCEDENTE_E`, `BOV_002_TRASLADO_E` y `BOV_002_TRASLADO_I`.

Cuatro de las 27 familias requieren seleccionar previamente el banco de liquidación. La preparación también valida el tipo, concepto, cuenta o rol que corresponda antes de emitir el payload. Si la familia ya existe, el flujo de alta inicial se detiene y el historial se conserva.

| Familias | Debe → Haber | Acción |
|---|---|---|
| `DOT_CAJA`, `DEV_CAJA`, `DOT_ATM`, `CAJA_DEPOSITO` | Según semilla E4-01 | Ya configuradas. Verificar vigencia. |
| `CAJA_FALTANTE`, `ATM_FALTANTE` | `19902505` → `11010510` o `11010515` | Registrar y aprobar. |
| `CAJA_SOBRANTE`, `ATM_SOBRANTE` | `11010510` o `11010515` → `299005` | Registrar y aprobar. |
| `BOV_<agencia>_AJUSTEFALTANTE_E`, `BOV_<agencia>_AJUSTESOBRANTE_I` | `19902505` → `11010505`; `11010505` → `299005` | Registrar y aprobar por agencia. |
| `BOV_<agencia>_PROVISIONEXTERNA_I`, `BOV_<agencia>_ENVIOEXCEDENTE_E` | Provisión: `11010505` → banco; excedente: banco → `11010505` | Indicar por agencia y evento el banco aprobado entre `110305`, `110310`, `110315` y `110320`. Aplica a liquidación bancaria confirmada. |
| `BOV_<agencia>_TRASLADO_E`, `BOV_<agencia>_TRASLADO_I` | Salida: `19080505` → `11010505`; ingreso: `11010505` → `19080505` | Registrar ambos sentidos de las agencias que participan. El traslado utiliza versiones si ambas etapas tienen una seleccionable en la misma fecha contable. Durante un corte parcial conserva la ruta anterior para ambas. |
| `RET_EFECTIVO_CAJA`, `RET_EFECTIVO_ATM`, `DEV_ATM` | Retiro: `CAPITAL` → efectivo. Devolución: `11010505` → `11010515` | Registrar configuración. La escritura del canal sigue pendiente. |
| `CUENTAS_TRANSFERENCIA_INTERNA`, `CUENTAS_COMISION` | `CAPITAL` → `CAPITAL` destino o ingreso de la tarifa | Registrar. `REP-TDB` está inactiva y la nueva restricción impide reactivarla sin ingreso válido. |
| `CREDITO_DESEMBOLSO_CUENTA`, `CREDITO_PAGO_CUENTA` | Desembolso: `CARTERA` → `CAPITAL` destino. Pago: `CAPITAL` → `CARTERA` e `INTERES_POR_COBRAR` | Registrar la variante principal e interés previamente devengado. |
| `CUENTAS_INTERES_DEVENGO`, `CUENTAS_INTERES_CAPITALIZACION`, `CREDITO_INTERES_DEVENGO` | `INTERES_GASTO` → `INTERES_POR_PAGAR`; obligación → `CAPITAL`; `INTERES_POR_COBRAR` → `INTERES_GANADO` | Registrar. |
| `CUENTAS_RETENCION`, `CUENTAS_LIBERACION`, `CUENTAS_RECLASIFICACION` | `CAPITAL` ↔ `RESTRINGIDO` para las primeras dos | Ya existen. Cotejar sus líneas antes de proponer versiones. |
| `CREDITO_SEGURO_COBRO_CUENTA` | `CAPITAL` de cuenta de cargo → `25909005` | Registrar para el cargo autónomo de desgravamen. |
| Reverso | Espejo de líneas originales | Usar el motor de reversos de la operación. |

## Ejecución posterior a la revisión

1. Verificar AC-01/E4-01, E2-01, E3-05 y E0-08 como prerrequisitos. Tras las migraciones de Cuentas de `develop`, aplicar por orden `202611251500_asientos_plantilla_uso.up.sql` y `202611251501_rep_tdb_cuenta_ingreso.up.sql`. La primera crea un índice y la segunda instala un disparador. Luego desplegar el backend que admite las familias BOV.
2. En SSMS, revisar los tipos y conceptos equivalentes. Completar `@Reusar` en `scripts/sql/registrar_catalogos_e403.sql` cuando se identifique un equivalente con otro código. Ejecutar el archivo con autorización DBA. Crea únicamente tipos y conceptos faltantes. Devuelve `CatalogoJSON` con los IDs resultantes. En Bóveda reutiliza el tipo de la regla existente cuando hay una.
3. En `scripts/sql/preparar_cobertura_e403.sql`, pegar `CatalogoJSON` en `@Catalogo`, indicar una fecha futura en `@VigenciaDesde` y cargar el banco autorizado por operación y agencia en `@Exterior`. Ejecutar y revisar contrapartidas, roles y familias existentes.
4. Preparar un archivo `manifiesto.json` con un arreglo. Para cada fila de la segunda salida en `LISTA_PARA_SOLICITUD`, incluir `{"idTipoAsiento": <IdTipoAsiento>, "borrador": <objeto BorradorE403>}`. Para Bóveda, incluir directamente cada objeto no nulo de `BorradorVinculoVersionado`. Usar ambas etapas de traslado y una fecha compatible por grupo. Conservar el manifiesto y la salida para revisión.
5. Revisar el manifiesto con `python scripts/registrar_plantillas_e403.py manifiesto.json --url <base-api-con-api-v1>`. Añadir `--registrar` para enviar efectivamente las solicitudes. El script pide el token del contador solicitante sin mostrarlo. Cada POST aceptado devuelve `idPlantillaAsiento` e `idSolicitud`. Una repetición consulta por código, verifica fecha, tipo, concepto y líneas y recupera la solicitud o envía el borrador pendiente que corresponda. Ante datos distintos, se detiene para revisión.
6. Otra persona, con permiso `con-plantilla-aprobar` y alcance sobre la agencia cuando aplique, revisa el objeto en la cola E0-08 y aprueba en el frontend o en `POST /api/v1/aprobaciones/{idSolicitud}/aprobar` con el comentario de revisión. La fecha debe seguir siendo futura al aprobar.
7. Consultar `GET /api/v1/contabilidad/reglas-contables?fecha=YYYY-MM-DD&agencia=001` con la fecha aprobada. Verificar la selección por familia y agencia. Probar un traslado de laboratorio y comprobar dos movimientos, dos asientos, dos versiones referenciadas y neto cero en `19080505`. Cuentas y Crédito pueden tener reglas vigentes y todavía carecer de un consumidor conectado.

La familia `BOV_<agencia>_<operación>_<lado>` contiene la asociación por agencia en su identidad. El backend valida el ámbito y la matriz de líneas y lo lleva a la solicitud E0-08. La operación actual de traslado confirma ambos extremos en una misma transacción. Si se implementa despacho y recepción asíncrona, guardar la ruta y el contexto de la solicitud desde el despacho.

Los pasos 2 a 6 son acciones explícitas posteriores a la revisión. El arranque del backend y los workflows de despliegue no invocan los scripts de registro ni crean solicitudes E0-08. Las dos migraciones de este cambio tampoco insertan, activan ni programan plantillas.

## Validaciones pendientes

La suite general del backend registró 4.614 pruebas aprobadas y 468 omitidas (`pytest tests -q -rs`). El resumen agrupa las omisiones por el motivo reportado.

| Omisiones | Requisito |
|---|---|
| 153 | Base de prueba no configurada, escritura deshabilitada o CooperativaDB con E3-05 requerida. |
| 26 | Laboratorio Bóveda opt-in. Estas 26 pruebas se ejecutaron por separado en SQL Server local. |
| 26 | Laboratorio y manifiesto de E0-08. La prueba de rollback DDL también se ejecutó por separado. |
| 12 | Manifiesto QA y acceso autorizado al ambiente Azure de desarrollo. |
| 251 | Otros laboratorios opt-in y bases descartables. Incluyen ATM, organización, parámetros, clientes, cuentas, productos y numeración. |

Antes de ejecutar en CooperativaDB, ensayar el despliegue sobre una copia restaurada. Verificar permisos DDL, antecedente de las migraciones, equivalencias de tipos y conceptos, vigencias, asignaciones E3-05 y la categoría y cuenta de ingreso de las tarifas. Cotejar los asientos históricos y los traslados por agencia, incluidos sus vínculos, saldos en tránsito y reintentos durante el corte parcial. Probar el ciclo de solicitud y aprobación con las dos bases restauradas y las identidades de ensayo. Mantener #434 abierta hasta verificar los consumidores financieros pendientes de extremo a extremo.

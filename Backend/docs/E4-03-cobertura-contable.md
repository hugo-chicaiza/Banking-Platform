# Consulta central y cobertura E4-03

`GET /api/v1/contabilidad/reglas-contables` usa la autorización de consulta de plantillas y el alcance de agencia de lectura para Bóveda. Acepta `fecha` y `agencia`. Por defecto resuelve la fecha con el calendario contable. Los identificadores `plantilla:<id>` y `boveda:<agencia>:<tipo>:<naturaleza>` distinguen las dos fuentes. El listado histórico de plantillas sigue disponible con su contrato anterior. La interfaz cliente debe cambiar a la consulta central para mostrar ambas fuentes.

La vigencia de una plantilla representa la versión seleccionada por el motor en la fecha pedida. En Bóveda se muestra si la fila está configurada y habilitada. `CONECTADA` acredita un consumidor en el código integrado, y `Usada` acredita un asiento vinculado a esa versión. Un consumidor sin referencias en la BD puede no haberse ejecutado desde su despliegue. Revisar auditoría de despliegue, operaciones posteriores al despliegue y tipos de asiento antes de concluir qué explica los ceros en Azure. BOV-04 y BOV-06 escriben por su propio adaptador, con referencia al asiento desde el movimiento, y quedan fuera de ese conteo por versión.

## Matriz para aprobación

| Evento | Plantilla o ruta prevista | Debe | Haber | Dependencia |
|---|---|---|---|---|
| Dotación y devolución de ventanilla | `DOT_CAJA`, `DEV_CAJA` | Ventanilla o bóveda receptora | Bóveda o ventanilla emisora | Consumidores integrados. Probar trazabilidad de versión contra operación nueva. |
| Traslado de bóvedas | `PlantillaBoveda`, `Traslado` E/I | Egreso `19080505`. Ingreso `11010505`. | Egreso `11010505`. Ingreso `19080505`. | Configuración confirmada para 001/002. Mantener ambas etapas y sus movimientos vinculados. |
| Provisión externa y excedente | `PlantillaBoveda`, `ProvisionExterna` I / `EnvioExcedente` E | Efectivo o contrapartida externa | Contrapartida externa o efectivo | BOV-04 integrado. Contabilidad debe aprobar las contrapartidas y filas por agencia. |
| Faltante de Bóveda, Caja y ATM | `AjusteFaltante` E para Bóveda | `19902505`, sujeto a validación por custodio | Auxiliar del custodio | BOV-06 integrado. Falta regla por agencia y productor de ajuste en los demás canales. |
| Sobrante de Bóveda, Caja y ATM | `AjusteSobrante` I para Bóveda | Auxiliar del custodio | CUC `299005` si es cuenta hoja aprobada | Falta confirmar imputabilidad y asignación. BOV-06 integrado. |
| Dotación y devolución ATM | `DOT_ATM` y familia de devolución por aprobar | Dotación `11010515`. Devolución `11010505`. | Dotación `11010505`. Devolución `11010515`. | Falta confirmación operativa que actualice ambos inventarios y llame al motor. |
| Retiro de ventanilla / ATM | Familias de retiro por aprobar | `PRODUCTO/CAPITAL` base `PRINCIPAL` | `11010510` o `11010515` base `PRINCIPAL` | Ventanilla requiere numeración, catálogos de canal y país, tipos de movimiento, registro de comisiones y proveedor financiero. ATM requiere confirmación de dispensación y reconciliación de reintentos. |
| Transferencia interna | Familia por canal | `PRODUCTO/CAPITAL` | `CONTRAPRODUCTO/CAPITAL` | Requiere productor con ambos extremos y una clave por confirmación. |
| Comisión | Líneas de la operación o familia para cobro autónomo | Cuenta del cargo | Cuenta configurada en la tarifa y pasivo fiscal si aplica | Clasificar la tarifa sin cuenta. Validar las dos tarifas de `549005` individualmente. |
| Desembolso y pago de crédito | Familias por hecho | Desembolso `CARTERA`. Pago medio de cobro. | Desembolso medio de abono. Pago `CARTERA` y componentes aprobados. | Resolver situación, condición y tramo desde E3-05. Falta productor y matriz de conceptos por producto. |
| Intereses | Familias de devengo y pago | Ahorro `INTERES_GASTO`, crédito `INTERES_POR_COBRAR`. | Ahorro `INTERES_POR_PAGAR`, crédito `INTERES_GANADO`. | El pago liquida la obligación o el derecho devengado. Requiere confirmar productor, calendario y regla de reconocimiento. |
| Retenciones, liberación y reclasificación | Familias existentes `CUENTAS_*` | Según líneas vigentes y subtipo | Según líneas vigentes y subtipo | Consumidores E6-05 y E6-06 integrados. Confirmar vigencia y roles efectivos en el ambiente. |
| Seguro | Componente del hecho financiero o familia autónoma | Cuenta de cargo aprobada | Cuenta configurada para el seguro | Validar contrato, devengo y liquidación. E3-05 aporta configuración, el productor debe seleccionarla. |
| Reversos | Espejo del original | Haber original | Debe original | Reutilizar el vínculo único de reverso. Conservar importes, agencia y trazabilidad. |

Las filas propuestas son insumos para el flujo de versiones y aprobación E0-08. Formar el borrador con cuentas ya resueltas, ejecutar simulación con importes positivos y cero, y aprobar con otro operador. Para Bóveda se requiere un mecanismo de alta por agencia con autorización y doble control antes de cargar reglas nuevas.

El endpoint de E4-03 admite un concepto existente al crear la primera versión de las familias habilitadas de Caja, ATM, Cuentas, Crédito y Bóveda. El backend fija el módulo contable. La solicitud pasa por E0-08 y el borrador permanece inactivo tras su creación.

Los movimientos históricos 253 y 2 permanecen como excepciones de conciliación. Investigar por solicitud, contraparte, movimiento relacionado y asiento antes de elaborar un diagnóstico de su origen. Los movimientos 419 y 420 sirven de referencia para preservar efectivo en tránsito. Mantener los asientos 879/880 y controlar que un reintento de la solicitud devuelva el resultado previo. El script `scripts/sql/validar_cobertura_contable_e403.sql` permite contrastar uso, tarifas y cuentas sin escribir en BD.

## Borradores de ampliación y decisiones contables

`scripts/sql/preparar_cobertura_e403.sql` genera líneas, coteja detalles existentes y produce el JSON que acepta `POST /api/v1/contabilidad/tipos-asiento/{id}/plantillas` para las familias nuevas que cuenten con tipo y concepto aprobados. Es repetible y no escribe en tablas de negocio. Si detecta una familia existente, conserva el identificador y el historial y devuelve sus líneas para comparación. Para las filas BOV genera una matriz de revisión por agencia. La carga directa por SQL omitiría el actor autenticado, la huella y el segundo aprobador de E0-08. Los cambios de catálogo se tramitan desde el endpoint.

| Regla | Borrador | Condiciones de configuración |
|---|---|---|
| Faltante de Caja, ATM y Bóveda | Debe `19902505`; Haber `11010510`, `11010515` o `11010505` según custodio | Confirmar tipo y concepto. En Bóveda, aprobar el vínculo por agencia. |
| Sobrante de Caja, ATM y Bóveda | Debe efectivo del custodio; Haber `299005` o un auxiliar existente de esa rama | Confirmar cuenta hoja activa e imputable. Si la cuenta CUC es hoja, basta esa cuenta. |
| Provisión externa | Debe `11010505`; Haber contrapartida externa confirmada por agencia | Identificar entidad, cuenta de liquidación y momento del hecho. |
| Envío de excedente | Debe contrapartida externa confirmada por agencia; Haber `11010505` | Identificar si representa abono efectivo en cuenta propia o despacho previo a la liquidación. |
| Transferencia interna | `PRODUCTO/CAPITAL` → `CONTRAPRODUCTO/CAPITAL` | Confirmar tipo y concepto. Los IDs de ambas cuentas cliente permanecen en la operación aunque compartan auxiliar. |
| Comisión de cuenta | Debe `PRODUCTO/CAPITAL`; Haber cuenta de ingreso resuelta de la tarifa | La cuenta faltante afecta a esa tarifa, y una comisión sin IVA incluido se puede configurar con este borrador. Para tarifas gravadas, aprobar la descomposición del cargo y su cuenta fiscal. |
| Crédito con abono o cargo a cuenta | Desembolso: `CARTERA` al Debe, `CAPITAL` del contraproducto al Haber. Pago: `CAPITAL` al Debe por principal e interés y `CARTERA` / `INTERES_POR_COBRAR` al Haber | Esta variante cubre principal e interés previamente devengado. Mora, tributos, pago en efectivo y otros componentes requieren sus propias bases y contrapartidas aprobadas. |
| Intereses | Ahorro: devengo y capitalización. Crédito: devengo ordinario | Resolver roles de E3-05 para cada producto y fecha. Los restringidos y el interés en suspenso se reconocen por sus roles específicos cuando el evento aplique. |
| Retención y liberación | `CAPITAL` ↔ `RESTRINGIDO` | Comparar con las dos familias ya desplegadas. Usar la regla únicamente para reclasificación efectiva del pasivo. |
| Prima de desgravamen con cargo autónomo | `CONTRAPRODUCTO/CAPITAL` al Debe y `25909005` al Haber | Verificar la cuenta configurada para el seguro y confirmar el cargo autónomo. Las primas retenidas en desembolso deben formar parte del asiento del desembolso. |

CUC segmento 1. `199025` es deudora y `19902505` ya existe como auxiliar de faltantes. `299005` es acreedora y representa la obligación por sobrantes. Para separar custodios, usar la dimensión operativa siempre que el plan permita usar la cuenta hoja. La evidencia actual no exige un auxiliar nuevo. Si `299005` resulta agrupadora sin una hoja utilizable, el padre sería `299005`, la naturaleza **acreedora** y la justificación sería identificar el pasivo conciliable por sobrantes. El código concreto requiere el inventario y la política de numeración de auxiliares de la entidad.

Para efectivo externo, la rama `1103` puede corresponder cuando existe un saldo en una entidad financiera y se identifica su titularidad. La subcuenta depende de la entidad y del producto de liquidación. El CUC describe `1105` en términos de remesas y efectos de cobro. No se debe trasladar automáticamente a esa rama el efectivo interno en tránsito ya configurado en `19080505`. Preservar ese auxiliar en el traslado existente y presentar su clasificación a Contabilidad si corresponde revisar el mapeo regulatorio. Fuente: [Catálogo Único de Cuentas SEPS](https://www.seps.gob.ec/catalogo-unico-de-cuentas-esfps/).

## Migración gradual de PlantillaBoveda

1. Introducir una asociación administrada entre agencia, operación, naturaleza y familia versionada. El vínculo y su activación deben quedar sujetos a E0-08, con identidad de los dos actores y huella que cubra la agencia y la familia. La primera versión reproduce las dos líneas de la regla original. Las contrapartidas distintas por agencia se resuelven con familias vinculadas por ámbito.
2. Comparar en lectura, para la fecha contable, ambas resoluciones de cuentas y tipo. Empezar por `Traslado` en 001/002 con dos hechos. En egreso, Debe `19080505` y Haber `11010505`. En ingreso, el espejo desde tránsito. La asociación debe habilitarse para ambos lados antes de enviar solicitudes nuevas al motor versionado. Para cada solicitud conservar el mecanismo elegido desde el despacho hasta la recepción.
3. Hacer el corte por agencia y operación. Resolver una sola ruta bajo la transacción que bloquea la solicitud. Clave estable por solicitud y etapa, con huella para distinguir un reintento de una solicitud inconsistente. Cada movimiento conserva la bóveda y el asiento vinculado. Cada asiento nuevo conserva el ID de versión elegida y la agencia de la etapa. Ante una regla versionada activa pero inválida, fallar y revertir la operación. El adaptador anterior se aplica a ámbitos aún no migrados.
4. Verificar paridad, saldos en tránsito por solicitud, acceso por agencia, rollback y replay concurrente. Mantener las reglas anteriores disponibles para conciliación y las solicitudes iniciadas con ellas hasta su cierre. Retirar el adaptador cuando todas las agencias y operaciones estén migradas y el tránsito anterior haya conciliado. Los asientos 879/880 y los demás históricos conservan sus referencias.

## Reversos

`asientos.reversar` lee los movimientos del ID original, conserva cuenta, monto y agencia por línea y cambia el lado. Genera una cabecera con `IdAsientoReversion` hacia el original y sin `IdPlantillaAsiento`. Un original ligado a una transacción exige las referencias de la transacción original y la del reverso. El bloqueo y la unicidad impiden un segundo espejo. El consumidor sigue siendo responsable de revertir la operación de negocio en la misma transacción.

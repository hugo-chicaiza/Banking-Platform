# Evidencia de E4-01, #380 y #434

## Alcance y reproducción

El catálogo del laboratorio contiene las 32 familias seleccionables en CooperativaDB Dev para la fecha contable 27/11/2026. Los casos fijan códigos de familia, tipo, concepto, cuentas y roles. Los IDs se resuelven en la proyección SQL local. Las cuentas dinámicas representan ejemplos de resolución para probar el contrato del motor. La prueba integral de un productor debe demostrar además la resolución E3-05 con su subproducto y contexto reales.

Con las capturas locales requeridas por `e201_sql_lab.py` en `E201_FIXTURES`, ejecutar `e201_corte_atomico_lab.py` para crear una base descartable. Dirigir `E201_REPORT` a una ruta temporal. Desde `Backend`, con `PYTHONPATH` apuntando a ese directorio:

```powershell
python tests/integration/e401_sql_lab.py CooperativaDB_E201_Lab_<sufijo> tests/integration/e201_sql_lab.py
```

El laboratorio usa las rutinas nativas de numeración y contabilización disponibles en la proyección SQL. Carga solamente los datos de prueba que faltan en la copia, conserva los cuatro casos de semilla e instala en la copia el disparador de cuenta hoja que ya está en develop. La prueba por familia compara el número con la salida de `usp_GenerarNumeroAsiento`, el estado y totales contabilizados, el ID de versión, las líneas y los deltas de hojas y ascendientes. Vuelve a invocar el evento y comprueba el mismo asiento. Después revierte y comprueba que el asiento, sus líneas, el registro de negocio de prueba y los deltas desaparezcan. El ensayo existente conserva el caso concurrente con commit y el rechazo nativo de un asiento descuadrado después de escrituras parciales.

Resultados sobre la rama basada en `4089d27`. El ensayo SQL local pasó las 32 familias, la sustitución y los casos negativos. La suite completa pasó 5.001 pruebas y omitió 471 según su configuración. La cobertura con ramas fue 61 % para Contabilidad en la suite completa. En el ensayo SQL fue 85 % para `asientos.py` y 93 % para `e401_catalogo_lab.py`. Ruff y Pyright pasaron.

## Criterios de aceptación

| Issue y criterio | Evidencia del motor SQL local | Simulación e integración de productor |
| --- | --- | --- |
| #380 AC1 · Depósito de 100,00 | `e401_sql_lab.py` comprueba Debe 11010510 y Haber 21013505, comisión cero y rollback. | CAJA_DEPOSITO está en catálogo. Caja y Transacciones deben demostrar depósito real, vínculo a transacción y commit conjunto. |
| #380 AC2 · Plantilla inexistente | Ensayo SQL de PLANTILLA_NO_DEFINIDA y rollback del registro de negocio de prueba. | Cada productor debe demostrar que sus propios cambios quedan revertidos. |
| #380 AC3 · Idempotencia | Reintento y saldos por familia en `e401_catalogo_lab.py`. Concurrencia y estado persistido en `e401_sql_lab.py`. | Cada productor conserva su clave y huella entre reintentos. |
| #380 AC4 · Comisión cero | El caso de semilla omite las dos líneas. El catálogo también ejerce una comisión positiva. | La selección de tarifa y exoneración corresponde al productor. |
| #380 AC5 · Tipos automáticos | 32 familias con líneas y contabilización real del laboratorio. El catálogo se fija por código en `e401_familias.json`. | Las 25 simulaciones de Swagger referenciadas en el PR #544 son evidencia de simulación. La adopción real por tipo depende de los productores y del alcance indicado abajo. |
| #380 AC6 · Espejo posterior | Ensayo SQL de fecha, enlace, original REVERSADO y saldo. | Los módulos de origen deben acreditar reversión del negocio y su enlace cuando corresponda. |
| #380 AC7 · Segundo reverso | Ensayo SQL de rechazo ASIENTO_YA_REVERSADO. | El canal conserva sus reglas de reversión operativa. |
| #380 AC8 · Vigencia | Dos fechas contables cruzan la sustitución v1 → v2 de CAJA_DEPOSITO. Se compara el ID de la versión con la cabecera de cada asiento. | El catálogo Dev acredita disponibilidad de familias por fecha. El productor debe resolver la fecha contable efectiva. |
| #434 · Servicio interno | `generar_asiento` y `reversar` usan la conexión del productor. | Caja y Cuentas ya tienen consumidores. Bóveda usa su adaptador. Ventanilla financiera, ATM financiero y Crédito conservan sus entregas pendientes. |
| #434 · Transacción y rollback | Reversión por familia y rollback ante fallo de contabilización nativa. | Falta ejecutar los productores pendientes con sus propias escrituras. |
| #434 · Número y contabilización oficiales | Número comparado con la rutina nativa y estado CONTABILIZADO con líneas, totales y saldos. | La inspección de Azure acredita presencia de los procedimientos. |
| #434 · Cuadre e imputabilidad | Ensayos negativos de descuadre y cuenta no imputable. Se conserva el criterio de imputación actual. | El cierre de #371 decide la política futura. |
| #434 · Pruebas por tipo y período cerrado | Catálogo SQL de 32 familias y ensayo de período cerrado. | El cierre persistente de un día hábil sigue en E4-06. |

## Tipos sin plantilla E4-01 seleccionable en Dev

| Tipo activo | Trabajo de Contabilidad | Dependencia |
| --- | --- | --- |
| `ATM_FALTANTE` | Candidato a completar con el tipo existente. Confirmar el auxiliar `19902505` frente a `19902515` y simular el asiento del faltante aprobado. | ATM certifica el productor del cuadre y el criterio aplicado. |
| `CREDITO_DESEMBOLSO` | Preparar el caso de una banda con principal, neto y SOLCA reutilizando el tipo si el concepto y contrato coinciden. | Crédito define reparto multibanda, transacción y reverso. La regla general espera esa definición. |
| `BOVEDA_PROVISION` | Cotejar la regla histórica y el banco por agencia antes de preparar la versión. | Bóveda confirma recepción efectiva y liquidación bancaria. |
| `BOVEDA_EXCEDENTE` | Preparar la dinámica contable una vez confirmadas las etapas y contrapartidas. | Bóveda distingue salida física y abono bancario. |
| `BOVEDA_TRASLADO` | Probar despacho y recepción por separado con efectivo en tránsito. Evaluar reutilización del tipo para ambas familias. | Bóveda debe emitir ambos eventos y acreditar la recepción del destino. |
| `CONTA_PAGO_RETENCIONES` | Revisar los asientos históricos y la ruta institucional antes de decidir si corresponde automatizar. | Validar el evento de pago, la obligación y la contrapartida con el dueño del flujo. |
| `CONTA_PAGO_SEGUROS` | Conciliar los asientos históricos con la ruta manual del pago institucional y distinguir el devengo de la prima. | Confirmar el evento de pago y si seguirá la ruta E4-04. |

Fuentes. [#380](https://github.com/hugo-chicaiza/Banking-Platform/issues/380) · [#434](https://github.com/hugo-chicaiza/Banking-Platform/issues/434) · [PR #544](https://github.com/hugo-chicaiza/Banking-Platform/pull/544) · [Catálogo confirmado](../../MATRIZ_MAESTRA_CONTABLE.md#inventario-de-las-25-versiones-aprobadas-en-azure-dev)

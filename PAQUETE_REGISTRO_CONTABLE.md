# Paquete de registro y aprobación E4-03

Corte de catálogo de CooperativaDB dev del 26 de noviembre de 2026. Los códigos de la tabla están listos para preparar el registro dentro del alcance indicado. La configuración en Azure sigue pendiente de autorización. El motor consume una familia cuando un productor la invoca para un hecho confirmado. Registrar o aprobar una familia no habilita un producto.

## Registro por paquete

| Paquete | Familias | Alcance de aprobación |
| --- | --- | --- |
| BASE | `RET_EFECTIVO_CAJA`, `CAJA_FALTANTE`, `CAJA_SOBRANTE`, `CREDITO_PAGO_CUENTA` | Tipos, conceptos y cuentas ya existen en la lectura dev. Retiro por principal, diferencias aprobadas y pago de principal e interés previamente devengado. |
| ACTUAL | `RET_EFECTIVO_ATM`, `DEV_ATM`, `ATM_SOBRANTE`, `CUENTAS_TRANSFERENCIA_INTERNA`, `CUENTAS_COMISION`, `CUENTAS_INTERES_DEVENGO`, `CUENTAS_INTERES_CAPITALIZACION`, `CREDITO_INTERES_DEVENGO`, `CREDITO_SEGURO_COBRO_CUENTA` | Compatible con la lista actual del editor tras crear los metadatos indicados. Comisión autónoma sin impuesto, capitalización sin retención fiscal y seguro autónomo. Aplicar las variantes solo donde coincidan las capacidades y condiciones aprobadas. |
| AMPLIACION | `APORTE_CERTIFICADO`, `APORTE_REDENCION_CAJA`, `APORTE_REDENCION_AHORRO`, `RED_COMISION_CAUSADA`, `RED_INTERCHANGE_GANADO`, `CON_DEPOSITOS_NO_CUBIERTOS_ALTA`, `CON_DEPOSITOS_NO_CUBIERTOS_BAJA` | Requiere el backend ampliado y sus metadatos. Las bases ya son compatibles con el frontend. |
| PRIMA | `CON_PRIMA_SEGURO_DEPOSITOS` | Requiere backend y registrador ampliados, además de incorporar `PRIMA_FIJA` y `PRIMA_VARIABLE` en el enum del frontend contable para la revisión visual. |
| ARQUEO | `BOV_001_AJUSTEFALTANTE_E`, `BOV_001_AJUSTESOBRANTE_I`, `BOV_002_AJUSTEFALTANTE_E`, `BOV_002_AJUSTESOBRANTE_I` | Usa el editor actual. Confirmar agencias activas y ventana con Bóveda antes de aprobar. Las cuatro reglas se limitan a ajustes de arqueo. |
| Existentes | `CAJA_DEPOSITO`, `CUENTAS_RETENCION`, `CUENTAS_LIBERACION`, `CUENTAS_RECLASIFICACION`, `DOT_CAJA`, `DEV_CAJA`, `DOT_ATM` | Conservar y verificar selección, líneas y productor. No enviar a alta inicial. |

Equivalencias comprobadas en dev. Ventanilla reutiliza tipo `CAJA_RETIRO` (4) y concepto `RET_EFECTIVO` (2). ATM reutiliza tipo `ATM_RETIRO` (16) y requiere concepto propio porque `RET_EFECTIVO` describe ventanilla. Caja reutiliza tipos `CAJA_FALTANTE` (6) y `CAJA_SOBRANTE` (5) y conceptos `AJUSTE_FALTANTE` (9) y `AJUSTE_SOBRANTE` (8). El sobrante ATM reutiliza el concepto genérico `AJUSTE_SOBRANTE` y requiere tipo específico. Transferencia interna reutiliza `CUENTAS_TRANSFERENCIA` (18), comisión `CUENTAS_COMISION` (19) y pago `CREDITO_PAGO` (15) con `PAGO_CREDITO` (6). El SQL resuelve los IDs en el destino por código y se detiene ante equivalencias requeridas ausentes, duplicadas, manuales o inactivas.

## Uso después de autorizar la ventana

1. **Previsualizar.** Ejecutar en la base destino con un día futuro acordado. El modo de consulta entrega un diagnóstico por familia y el JSON de BASE si conserva los cuatro pares disponibles. Reconciliar cualquier familia existente con su historial y preservar las versiones.
2. **Crear metadatos.** El DBA autoriza explícitamente la base y activa el modo de catálogo para el paquete seleccionado. El script da de alta únicamente códigos que figuran como nuevos. Cada manifiesto se genera completo o devuelve `NULL`. Copiar cada `ManifiestoJSON` a un archivo UTF-8 separado sin alterar líneas, orden ni IDs. Restablecer las variables de sesión a `NULL` al terminar.
3. **Simular.** Usar `POST /api/v1/contabilidad/plantillas/simulaciones` con roles y cuentas vigentes del producto. Probar pago desde cuenta con principal e interés, y con uno de los dos componentes en cero. Para aportes comprobar `3103` y para redención a ahorro el CAPITAL de destino. Revisar agencia y período en el ambiente.
4. **Solicitar y aprobar.** Usar el registrador oficial con origen autorizado. La primera persona registra la solicitud E0-08. La segunda revisa el detalle y aprueba en la cola, mientras la fecha siga siendo futura. Cotejar vigencia y roles con el módulo consumidor. Conservar ID de solicitud, versión, cuentas, evidencia de simulación y personas responsables.

```sql
-- Sesión de destino autorizada. Sustituir la fecha por la acordada.
EXEC sys.sp_set_session_context N'paquete_contable_vigencia', N'YYYY-MM-DD';
EXEC sys.sp_set_session_context N'paquete_contable_paquete', N'BASE';
-- Solo en el paso de alta de metadatos autorizado, en esa misma sesión.
DECLARE @base sysname = DB_NAME();
EXEC sys.sp_set_session_context N'paquete_contable_base', @base;
EXEC sys.sp_set_session_context N'paquete_contable_catalogo', 1;
```

El generador SQL escribe solo en `TiposAsiento` y `ConceptoContable` en el modo de alta. El ensayo recibe un directorio de salida para generar los cinco manifiestos con IDs locales fuera del árbol versionado. El [manifiesto BASE de dev](Backend/scripts/sql/e403-base-dev-vigencia-propuesta.json) usa los IDs comprobados para ese ambiente. La fecha propuesta es el 27 de noviembre de 2026 si la segunda aprobación se completa con día contable anterior. Consultar el calendario vigente y proceder según el [orden para Azure](RUNBOOK_AZURE_E403.md). [Generador SQL](Backend/scripts/sql/preparar_paquete_contable.sql) · [Verificador SQL](Backend/scripts/sql/verificar_manifiesto_contable.sql) · [Ensayo automatizado](Backend/tests/integration/paquete_contable_sql_lab.py)

### Posible mejora posterior

La vigencia sigue iniciando en un día contable futuro. Una eventual excepción intradía se limitaría a una primera versión para un hecho sin ruta contable anterior, con segunda aprobación independiente y revalidación bajo el mismo bloqueo transaccional que usa el motor. El selector tendría que comparar un instante efectivo auditable con la confirmación persistida del evento. Los hechos anteriores conservarían su ruta original o pasarían por regularización autorizada. Los reintentos conservarían el asiento y la versión ya registrados. Antes de habilitar la excepción, probar eventos demorados, aprobaciones concurrentes y cierre simultáneo, con día y período abiertos. [E4-03](https://github.com/hugo-chicaiza/Banking-Platform/issues/382) · [Cierre diario](https://github.com/hugo-chicaiza/Banking-Platform/issues/384)

La rama independiente `feat/contabilidad-e403-ampliacion` integra el editor, el registrador y el contrato. Desplegarla de forma autorizada antes de enviar AMPLIACION o PRIMA.

## Familias retenidas

| Conjunto | Estado |
| --- | --- |
| Diez de las 27 propuestas E4-03 | `ATM_FALTANTE`, `CREDITO_DESEMBOLSO_CUENTA`, las cuatro `BOV_*_PROVISIONEXTERNA_I` / `ENVIOEXCEDENTE_E` y las cuatro `BOV_*_TRASLADO_E/I` quedan fuera de los manifiestos. Las otras 17 están en BASE, ACTUAL y ARQUEO. |
| Traslado Bóveda | Conservar las cuatro reglas históricas. El registro de familias nuevas no separa despacho de recepción. Acordar el corte por traslado y agencia después de la implementación funcional. |
| Liquidación Mastercard | Los dos sentidos ensayados siguen parametrizados por banco de convenio. Falta determinar cuenta de liquidación y si una confirmación compensa simultáneamente partidas por pagar y cobrar. |
| Mastercard crédito | Cupo, compras, avances, pagos del ciclo, mora, cargos al titular y disputas requieren reconocimiento aprobado y productor. Las reglas de devengo y comisión de red se preparan para su alcance general. |
| Interbancarias, reclasificación y cartera | Mantener I01–I06 y C01/C06–C12/C14 pendientes según sus decisiones. Una regla de provisión o castigo exige conocer el tramo, la condición, las contrapartidas aplicables y el productor. |
| Otras variantes | Mantener pendientes ejecución judicial, interés restringido, depósito ATM, capitalización con impuesto, comisión gravada, cuota en efectivo, neteo en redención, entero de seguros/impuestos y pago manual de COSEDE según la matriz. |

## Decisiones de Contabilidad

| Decisión | Opciones o criterio para cerrarla |
| --- | --- |
| Ventana de registro | Aprobar paquetes, fecha futura, alcance de variantes y segunda persona. Fijar la fecha con el calendario contable de destino. |
| Faltante ATM | Elegir la hoja con justificación: `19902505` existe activa e imputable. `19902515`, citada en #102, no apareció en dev. Si debe distinguirse por auxiliar, autorizar alta bajo la rama de faltantes. |
| Bóveda | Ratificar `19902505` y `299005` en el paquete ARQUEO. Confirmar contrapartidas de provisión y excedente por agencia y transición desde las cuatro reglas históricas de traslado. Conservar `19080505` para despacho/recepción separados y especificar regularización autorizada. |
| Interés de depósitos y comisión | Resolver `410115` de #400 frente al mapeo E3-05 efectivo. Aprobar cuenta fiscal y bases por hecho. Las variantes de capitalización y comisión del paquete cubren operaciones sin esos componentes fiscales. |
| Crédito | Aprobar contrapartida y reconocimiento de mora, orden de imputación, cuentas de provisión/suspenso/castigo, y regla de reversión y recuperación. Para desembolso acordar componentes bruto/neto, SOLCA, seguros y cómo contabilizar varias bandas. |
| Certificados | Confirmar `3103` como hoja de aportes y criterio contable para compensar deudas en redenciones. Las tres familias cubren monto sin compensación. |
| Mastercard y redes | Aprobar banco o cuenta de liquidación por red y convenio, neteo mixto, partidas abiertas, reversos/contracargos y variantes definitivas de liquidación. Si se aprueba la operación de crédito, fijar orientación y hecho de registro/liberación del cupo sin duplicar el orden de consumo. |
| Interbancarias | Confirmar cuentas de salida, tránsito y banco; documentar la dinámica de `11050505`, la contrapartida para entrada no identificada y el tratamiento de comisión/reintegro. |
| Seguro de depósitos y cierre | Acordar base, tasas, calendario y banco del pago manual. Las reglas incluidas separan prima fija/variable y el ajuste de saldos no cubiertos por signo. El productor de cierre debe calcular las bases y conservar la conciliación. |

## Decisiones de los módulos consumidores

| Responsable | Decisión y evidencia que debe entregar |
| --- | --- |
| Productos y Cuentas | Capacidades por subproducto y canal, tasas, políticas de retención y elegibilidad. Para E3-06, conexión del checklist y revalidación en aprobación. Para E6-01, revalidación de apertura. |
| Caja, ATM y Transacciones | Confirmación física o financiera, IDs de operación, aplicación de cargos, reintento, revertir negocio y conservar la referencia al asiento. ATM define dispensación incierta, cuadre y devolución de custodia. |
| Bóveda | Fuente de evidencia de despacho, confirmación del custodio receptor, estados intermedios, parciales y diferencias. Acordar si la aprobación incluye evidencia de salida efectiva. Implementar separación de etapas y restringir el reverso operativo. |
| Crédito y Riesgos | Momento de reconocimiento, desglose efectivo del pago y desembolso, situaciones y tramos, mora, provisión y transiciones de cartera. Mantener referencia por hecho y conciliar con subledger. |
| Tarjetas, Redes y Tesorería | Confirmación operativa de si se ofrece Mastercard crédito. Si se aprueba, definir emisión/cupo, compra, avance, pago y ciclo de interés. Redes identifica la confirmación de cada partida, formato de liquidación, convenios y contracargos. |
| Interbancarias y Tesorería | Identidades y eventos de débito, aprobación, envío, confirmación, tránsito y devolución. Proveer contraparte, banco y archivos de conciliación. |
| Administración y QA | Identidades independientes y permisos configurados. Evidencia de autorización, reintentos, concurrencia y verificación de cada productor. |

Los identificadores de fila remiten a la matriz maestra de Contabilidad. Priorizar los paquetes con cuentas, alcance y responsables confirmados.

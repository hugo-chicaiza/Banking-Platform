# Contrato de integración contable

Contabilidad publica la matriz, configura reglas y valida el resultado. Cada módulo consumidor define la confirmación funcional, sus controles, permisos, idempotencia y persistencia. La frontera es el evento confirmado del productor. El motor recibe datos internos y usa la conexión del productor.

## Catálogo aprobado y alcance

El [inventario de Azure Dev](MATRIZ_MAESTRA_CONTABLE.md#inventario-de-las-25-versiones-aprobadas-en-azure-dev) registra las 25 versiones seleccionables desde la fecha contable 27/11/2026. Retiro de ventanilla (13), transferencia interna (21) y retiro ATM (23) reciben `PRINCIPAL`. La prima institucional (35) recibe `PRIMA_FIJA` y `PRIMA_VARIABLE`. Resolver por familia y fecha. Los IDs son evidencia de Dev.

La aprobación de una versión cubre las líneas registradas. El productor prueba la operación en su canal. La [matriz E3-06](MATRIZ_ACTIVACION_PRODUCTOS.md) requiere una exclusión explícita para las operaciones fuera de alcance y mantiene pendiente la capacidad permitida que carezca de regla o consumidor.

## Catálogo aprobado y alcance

El [inventario de Azure Dev](MATRIZ_MAESTRA_CONTABLE.md#inventario-de-las-25-versiones-aprobadas-en-azure-dev) registra las 25 versiones seleccionables desde la fecha contable 27/11/2026. Retiro de ventanilla (13), transferencia interna (21) y retiro ATM (23) reciben `PRINCIPAL`. La prima institucional (35) recibe `PRIMA_FIJA` y `PRIMA_VARIABLE`. Resolver por familia y fecha. Los IDs son evidencia de Dev.

La aprobación de una versión cubre las líneas registradas. El productor prueba la operación en su canal. La [matriz E3-06](MATRIZ_ACTIVACION_PRODUCTOS.md) requiere una exclusión explícita para las operaciones fuera de alcance y mantiene pendiente la capacidad permitida que carezca de regla o consumidor.

## Generar un asiento automático

| Parámetro de `OperacionContable` | Contrato |
| --- | --- |
| `codigo_plantilla` | Familia aprobada para el evento. El motor selecciona por fecha contable, estado del tipo y prioridad de versión. |
| `clave_evento` | Identidad estable y única de hasta 100 caracteres, sin espacios iniciales o finales. Incluir etapa si una orden produce varios asientos. |
| `id_agencia`, `id_fecha_contable` | Código de agencia de tres caracteres y fecha contable resuelta por calendario, en período abierto. |
| `id_usuario`, `fecha_hora` | Identidad interna auditada y marca horaria del evento. Acordar identidad de tareas programadas. |
| `importes` | Diccionario de bases de la versión vigente a `Decimal`, finitos, no negativos y con máximo dos decimales. Proveer una entrada por base, incluso cero para líneas opcionales. Cálculos de negocio de mayor precisión se redondean antes de invocar con política aprobada. |
| `id_transaccion` | Identificador de la transacción financiera cuando corresponda. Conservar la referencia del hecho si se trata de custodia u otro módulo. |
| `cuentas_por_rol` | Mapa interno `(origen, rol) → IdCuentaContable`. Usar PRODUCTO y CONTRAPRODUCTO para extremos distintos y `("COMISION", None)` para ingreso de la tarifa aplicada. FIJA se resuelve desde la plantilla. Resolver primero mediante E3-05, con contexto por rol y fecha. |

El motor registra ID de versión, sigue la numeración y contabilización nativas y verifica cuadre y hojas activas e imputables. Considera hoja al último nivel de la rama, incluidos códigos de cuatro o seis dígitos cuando cumplan. La repetición de la misma clave y huella devuelve el asiento previo. La misma clave con contexto diferente falla. El productor protege también el movimiento funcional y resuelve los reintentos con el contexto original. Resolver cuentas nuevas después de un cambio de vigencia para una clave ya usada puede provocar un conflicto correcto.

Para ampliaciones como un desembolso bruto con neto, SOLCA y seguro, preparar bases explícitas y probar la igualdad del total. El catálogo y el motor actuales soportan `FIJA`, `PRODUCTO`, `CONTRAPRODUCTO` y `COMISION`. Impuesto y seguro aportan cuentas en su configuración E3-05. Una cuenta dinámica adicional requiere un mecanismo acordado con Contabilidad y una actualización explícita del contrato. Las bases y los roles no se inventan en el consumidor.

El editor E4-03 admite `PRINCIPAL`, `COMISION`, `IMPUESTO`, `INTERES`, `MORA`, `SEGURO`, `DIFERENCIA` y `TOTAL`. Exige igual número de líneas Debe y Haber por base. Para el desembolso de 2.500,00 de #31, una versión candidata puede representar 2.487,50 con un par CARTERA → CAPITAL y 12,50 con un par CARTERA → SOLCA. La suma de las líneas de CARTERA es 2.500,00. Si intervienen varias bandas, el mapa actual solo permite una cuenta por clave `(origen, rol)`. Definir y ensayar la representación antes de integrar un asiento que requiera varias cuentas de CARTERA en el mismo extremo. El alta de familias fuera del manifiesto también debe verificar la lista de orígenes permitidos del editor.

Contabilidad simula las líneas y montos en E4-03, solicita versión mediante `POST /contabilidad/tipos-asiento/{id}/plantillas` y conserva ID de versión y solicitud de aprobación. Una segunda persona aprueba en E0-08. Verificar la selección mediante `GET /contabilidad/reglas-contables?fecha=YYYY-MM-DD&agencia=001` y cotejar las líneas de la versión efectiva. Estos endpoints operan bajo el prefijo `/api/v1`.

### Ejemplo A01, futuro adaptador de depósito

```python
from decimal import Decimal
from app.modules.contabilidad.asientos import OperacionContable, generar_asiento
from app.modules.contabilidad.cuentas_producto import cuenta_contable
from app.modules.contabilidad.service import resolver_id_fecha_contable
from app.modules.contabilidad.repository import obtener_por_id

# La transacción y el depósito confirmado pertenecen al módulo consumidor.
with engine.begin() as conn:
    id_dia = resolver_id_fecha_contable(conn, instante)
    fecha = obtener_por_id(conn, id_dia)["fecha"]
    capital = cuenta_contable(conn, id_subproducto, "CAPITAL", fecha)
    # id_transaccion corresponde al depósito persistido en esta conexión.
    id_asiento = generar_asiento(conn, OperacionContable(
        codigo_plantilla="CAJA_DEPOSITO",
        clave_evento=f"DEPOSITO:{id_transaccion}",
        id_agencia=agencia,
        id_fecha_contable=id_dia,
        id_usuario=actor_interno,
        fecha_hora=instante,
        importes={"PRINCIPAL": Decimal("100.00"), "COMISION": Decimal("0.00")},
        id_transaccion=id_transaccion,
        cuentas_por_rol={("PRODUCTO", "CAPITAL"): capital},
    ))
    # Guardar vínculo y confirmar cambios de saldo e inventario en este commit.
```

Para A04, el mapa contiene CAPITAL del origen como PRODUCTO y CAPITAL del destino como CONTRAPRODUCTO. El productor conserva ambos IDs de cuenta cliente y bloquea en orden consistente. Para C02, resuelve CARTERA con situación, condición y tramo, y CAPITAL de destino con el subproducto de la cuenta de abono. La familia C02 v1, ID 36, está aprobada y seleccionable en Azure Dev desde el 30/11/2026 para una sola banda. En esta versión, PRINCIPAL es el neto e IMPUESTO es SOLCA. El productor debe validar bruto = neto + SOLCA y rechazar antes del motor cualquier reparto con más de una banda positiva. El motor recibe una cuenta por rol y no detecta un reparto multibanda que el consumidor haya reducido a una sola cuenta. El productor real y el contrato multibanda siguen pendientes.

### Faltante de custodia ATM

`ATM_CUADRE` aprobado con un faltante efectivo positivo usa la familia `ATM_FALTANTE`, componente `DIFERENCIA`. En Azure Dev la configuración está completa: la v1, ID 37, aprobada y seleccionable desde el 30/11/2026, debita `19902515` y acredita `11010515`. El productor de ATM debe persistir la terminal, agencia y cuadre, usar una clave de evento estable por cuadre y confirmar ajuste y asiento en la misma transacción. El productor sigue pendiente. [Configuración y evidencia](Backend/docs/E4-01-atm-faltante.md)

### Reversiones y compensaciones

Usar `reversar(conn, id_asiento_original, motivo, actor=...)` dentro de la transacción de negocio. Si el original está ligado a una transacción, pasar `id_transaccion_original` y `id_transaccion_reverso`. El motor espeja líneas, conserva trazabilidad y protege la unicidad. El consumidor verifica elegibilidad, aprobación, fecha y restauración efectiva del negocio. Una devolución parcial, rechazo, contracargo de red o retorno físico tiene identidad y tratamiento propios cuando el contrato lo prevé.

## Bóveda

| Hecho | Asiento | Confirmación y propietario |
| --- | --- | --- |
| Solicitud, rechazo o cancelación antes de despacho | Sin asiento | Bóveda conserva identidad, motivo y auditoría. |
| Aprobación sin evidencia de salida física | Sin asiento en el diseño objetivo | Bóveda determina si aprobación y despacho deben coincidir en el proceso real y documenta la evidencia. |
| Despacho efectivo | Debe `19080505`, Haber `11010505` en origen | Bóveda confirma salida y actualiza únicamente el inventario de origen. Clave propia de despacho. |
| Recepción efectiva | Debe `11010505`, Haber `19080505` en destino | Custodio receptor confirma efectivo. Bóveda enlaza despacho y recepción y actualiza destino. La fecha contable de recepción puede diferir. |
| Diferencia, incidencia o retorno físico autorizado | Asiento de regularización especificado según evidencia | Bóveda certifica custodia. Contabilidad autoriza y concilia conforme a E4-04 o a regla específica aprobada. |

**Confirmación en el código actual.** El endpoint de aprobación llama a `ejecutar_movimiento_autorizado`, que aplica egreso e ingreso, vincula movimientos y resuelve la solicitud en la misma transacción. Por tanto la aprobación coincide con la salida **registrada**, y también con la recepción **registrada**. El código no acredita salida física ni confirmación independiente del custodio destino. La historia E7-13 sí exige esa confirmación. Bóveda conserva la responsabilidad de implementar la separación y acordar si el acto de aprobar incluye prueba de despacho.

Para el contrato objetivo, registrar ID de solicitud, identidad por etapa, agencia y custodia por extremo, denominaciones, monto y referencias contables. Ejemplo de claves `BOV-TRASLADO:42:DESPACHO` y `BOV-TRASLADO:42:RECEPCION`. Conciliar el saldo abierto de `19080505` por traslado y ambas agencias. Hasta la recepción confirmada queda saldo en tránsito. Bóveda define el manejo de parciales, discrepancias, custodia y retornos. El corte debe conservar una ruta coherente para cada traslado iniciado y verificar que el índice legado por solicitud y bóveda permite el diseño definido.

Restringir el reverso operativo genérico del traslado ejecutado o en tránsito. Mantener el mecanismo de regularización contable autorizado, con motivo, evidencia, segunda aprobación cuando aplique y referencias al hecho original. Una regularización contable no actualiza físicamente el inventario. En arqueos, contabilizar la diferencia aprobada. Mantener separados faltante y sobrante y comprobar cuentas por custodio.

## Criterios de entrega del consumidor

Entregar la referencia de historia, evento, fecha y módulos implicados, identificación y prueba de versión y cuentas, asiento contabilizado, conciliación contra subledger o inventario, retry sin duplicados y rollback en falla. Probar dos sesiones si el hecho exige aprobación. Incluir periodo cerrado, cuenta no imputable, falta de plantilla, reintento concurrente y un caso válido de corrección o reverso. Las pruebas de fin de día verifican partidas abiertas, efectivo y sus diferencias sin crear asientos implícitos.

[Motor E4-01](https://github.com/hugo-chicaiza/Banking-Platform/issues/380) · [Asientos manuales E4-04](https://github.com/hugo-chicaiza/Banking-Platform/issues/383) · [Traslado E7-13](https://github.com/hugo-chicaiza/Banking-Platform/issues/63) · [Solicitud BOV-04 en 905bec0](https://github.com/hugo-chicaiza/Banking-Platform/blob/905bec04fbafb41efe251d2150818cf7c7546cf4/Backend/docs/BOV-04-solicitudes-autorizacion.md)

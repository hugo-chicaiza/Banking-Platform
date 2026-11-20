# E4-01 Motor contable

`generar_asiento(conn, OperacionContable(...))` usa la transacción del llamador.
Pase una clave estable del evento, agencia, identidad interna, fecha contable,
importes Decimal y, para una transacción, su ID. Use el mismo contexto al
reintentar. El motor rechaza una clave reutilizada con otra huella.

Las plantillas AC-01 conservan sus IDs y detalles. La vigencia se elige con el
día contable y solo se consideran versiones activadas. Los roles se pasan como
un mapa interno de (origen, código de rol) a ID de cuenta, resuelto por el
módulo invocador desde su configuración. La comisión usa (COMISION, None).
Cada base indicada en las líneas debe aparecer en importes, aun con valor cero.
El motor omite los ceros, valida los auxiliares de ocho dígitos, cuadra,
numera con el procedimiento SQL nativo, contabiliza y actualiza saldo del
auxiliar y de sus ascendientes. Ante un error el llamador debe hacer rollback.

`reversar(conn, id_asiento, motivo, actor=...)` genera el espejo y conserva
las líneas originales. En un asiento asociado a una transacción, el adaptador
de la operación debe pasar el ID de la transacción original y del reverso como
parte de esa misma transacción. Se usa la fecha contable vigente de Ecuador.

## Matriz y consumidores

| Familia | Débito | Crédito | Consumidor |
|---|---|---|---|
| DOT_CAJA | 11010510 | 11010505 | CAJ-07 |
| DEV_CAJA | 11010505 | 11010510 | CAJ-15 |
| DOT_ATM | 11010515 | 11010505 | Disponible para el flujo de custodia ATM |
| CAJA_DEPOSITO | 11010510 | CAPITAL del producto | Disponible para el adaptador de ventanilla |

La matriz del depósito incluye la comisión definida en #380: débito CAPITAL
y crédito a la cuenta de ingreso de la comisión. Una comisión cero omite esas
dos líneas y no requiere resolver la cuenta de comisión. Consulte el día
contable en la misma conexión del módulo. CAJ-07 usa el ID de la dotación,
CAJ-15 el ID de la devolución, con los prefijos DOTACION_CAJA y DEVOLUCION_CAJA.
La integración conserva la autorización y el movimiento de efectivo existentes.

Para un consumidor nuevo, dentro de la transacción del movimiento:

```python
from decimal import Decimal
from app.modules.contabilidad.asientos import OperacionContable, generar_asiento

id_asiento = generar_asiento(
    conn,
    OperacionContable(
        codigo_plantilla="CAJA_DEPOSITO",
        clave_evento=f"TRANSACCION:{id_transaccion}",
        id_agencia=id_agencia,
        id_fecha_contable=id_fecha_contable,
        id_usuario=actor,
        fecha_hora=fecha_hora,
        importes={"PRINCIPAL": Decimal("100.00"), "COMISION": Decimal("0.00")},
        id_transaccion=id_transaccion,
        cuentas_por_rol={("PRODUCTO", "CAPITAL"): id_auxiliar_capital},
    ),
)
```

Obtenga el auxiliar del subproducto desde una configuración validada. El
llamador suministra los IDs de las cuentas resueltas. Propague las excepciones
hasta el bloque transaccional. Una plantilla ausente devuelve
PLANTILLA_NO_DEFINIDA. Un segundo reverso devuelve ASIENTO_YA_REVERSADO.

## Orden de instalación propuesto para Azure

1. Ensayar el corte E2-01 y conciliar el saldo antes y después sobre una copia
   restaurada. Aplicar 001 y 004 y ejecutar el corte autorizado durante la
   ventana de mantenimiento, con evidencia y dos identidades verificadas.
   Ejecutar 005_auxiliar_faltantes tras verificar los usos de 199025.
2. Aplicar en orden 20261111_ac01_01, 20261111_ac01_02,
   20261117_e401_versiones y 20261117_e401_versiones_semilla. Revisar preexistencias
   AC-01 antes de la instalación. La semilla falla si una familia inicial
   difiere y preserva las versiones previas.
3. Confirmar las cuatro plantillas, cuentas imputables activas y saldos del
   corte antes de desplegar la aplicación con CAJ-07 y CAJ-15. Las rutas
   requieren la semilla y revierten el movimiento si la contabilización falla.
4. Ejecutar los ensayos SQL locales y las pruebas de cada ruta. El ensayo de
   este repositorio usa una proyección del esquema, con catálogos mínimos de
   conceptos y tipos. La aprobación de los cambios en Azure queda a cargo del DBA.

## Dependencias de otros módulos

F-08 clasifica G-11 como descartada como brecha de migración. El proveedor de
ventanilla en develop sigue sin emitir los identificadores requeridos por
su contrato: NumeroComprobante, Secuencial, CodigoProcesamiento y, cuando
correspondan al canal, STAN, RRN y autorización. Los valores de consulta de
saldo ATM vienen del protocolo ATM y no especifican el contrato de caja.
Transacciones debe designar el generador y confirmar canal, país, tipos de
movimiento y registro y reverso de comisiones. Una vez resueltos esos
contratos, puede consumir CAJA_DEPOSITO usando el ejemplo anterior.
## Entrega y cumplimiento de #434

### Motor contable

El motor interno está terminado y verificado para el contrato de registro y
reverso implementado. `generar_asiento` y `reversar` se invocan como funciones
internas sobre la conexión SQL del llamador.

| Criterio de aceptación | Evidencia y alcance |
|---|---|
| Servicio interno sin endpoint | Verificado para el motor. Caja lo invoca y Bóveda usa su adaptador con las rutinas SQL compartidas. La adopción de ATM financiero, ventanilla y crédito sigue pendiente |
| Asiento y operación en la misma transacción | Verificado en el motor y en las integraciones habilitadas de Caja y Bóveda. El laboratorio verifica rollback de negocio ante rechazo del procedimiento contable. Cada nuevo consumidor debe demostrar esta propiedad en su operación real |
| Numeración y contabilización nativas | Verificadas con `usp_GenerarNumeroAsiento` y `usp_ContabilizarAsiento` en SQL Server local |
| Débitos iguales a créditos, cuentas imputables y calendario | Verificado para el alta y el reverso contables. Se cubren descuadre, cuentas no imputables, día inhábil y período cerrado |
| Pruebas por tipo de operación y casos negativos | Verificadas para el motor y las integraciones habilitadas. Las pruebas de plantilla y de prevalidación ATM acreditan esos componentes. Quedan pendientes las pruebas financieras de extremo a extremo de los tres consumidores bloqueados |

### Integraciones existentes

CAJ-07 y CAJ-15 llaman al motor con `DOT_CAJA` y `DEV_CAJA`. BOV-04 y
BOV-06 contabilizan con la matriz `PlantillaBoveda` y las rutinas SQL
compartidas. La matriz por agencia sigue siendo responsabilidad de
Contabilidad en cada ambiente.

### Integraciones pendientes y tareas para los módulos responsables

| Módulo | Operaciones integradas | Operaciones pendientes y dependencias | Verificación local |
|---|---|---|---|
| Caja | CAJ-07 dotación y CAJ-15 devolución usan `DOT_CAJA` y `DEV_CAJA` en la misma transacción SQL del movimiento. La clave contable usa el ID del movimiento. La devolución es un movimiento propio con plantilla, y la integración conserva las validaciones de custodia y jornada | El motor admite el espejo contable. No se identificó un endpoint bancario habilitado para anular estas operaciones como reverso | Pruebas CAJ-07 y CAJ-15, E4-01 y laboratorio combinado Caja/Bóveda |
| Ventanilla y TRX-03 | CAJ-09 depósito, CAJ-11 retiro y TRX-03 reverso tienen adaptadores y límites transaccionales existentes. Ventanilla verifica `RegistroUnico`; TRX-03 verifica el estado y la existencia del reverso. Las rutas conservan su protección por bandera y proveedor | El proveedor de dinero sigue sin configuración. Para depósito existe `CAJA_DEPOSITO`. Transacciones y Contabilidad deben confirmar numeración, canal, país, códigos de caja, comisiones y reversos, auxiliar CAPITAL por subproducto y matriz para retiro | Suites de rutas con proveedores simulados, rechazo de un asiento ausente y ensayo de `CAJA_DEPOSITO` con cuenta de prueba |
| ATM | Consulta de saldo, sesión y cambio de PIN no contabilizan dinero. Retiro ATM-03, transferencia ATM-05 y reverso ATM-08 tienen prevalidaciones y permanecen deshabilitados para escritura financiera. En el router actual no se encontró una ruta de depósito ATM | `DOT_ATM` está sembrada para custodia; no hay productor de dotación conectado. Para los flujos financieros faltan la matriz por operación y subproducto, idempotencia de la confirmación, comisiones, reglas de efectivo y dispensación y el enlace del reverso con su operación y asiento original | Pasaron los laboratorios locales de preparación, duplicados y bloqueos de ATM-03/05/08. ATM-02 quedó bloqueado por el esquema local de Cambio PIN y la ubicación de su captura de esquema. La plantilla `DOT_ATM` se prueba en E4-01 por separado |
| Bóveda | La ejecución autorizada BOV-04 cubre provisión, envío de excedente y traslado. BOV-06 registra ajustes de arqueo aprobados. El adaptador usa `PlantillaBoveda` por agencia, tipo y naturaleza y comparte numeración, contabilización y actualización de saldos con E4-01. Inventario, movimientos y asiento comparten transacción. Las solicitudes y la aprobación del arqueo protegen contra duplicados | Contabilidad debe confirmar la matriz por agencia en el ambiente de destino. No se identificó un reverso financiero BOV dedicado | Laboratorio SQL de concurrencia, reintentos, rollback, arqueos, traslados y conciliación con Caja |
| Crédito | Condiciones, solicitudes y simulación de amortización no generan asientos | Faltan flujos financieros de desembolso, cobro y reverso, más una matriz aprobada por producto/subproducto para principal, interés, mora, impuestos y comisiones según corresponda. Crédito debe proveer la transacción de negocio y sus claves de reintento | Pruebas de Crédito para condiciones y simulación. Sin integración financiera que ejecutar |

El ensayo E4-01 comprueba período cerrado, reverso con auxiliar no imputable,
espejo válido, idempotencia concurrente y rollback cuando el procedimiento
nativo rechaza un descuadre después de escribir la cabecera y una línea.
Ventanilla y TRX-03 abortan la transacción si el proveedor contable no devuelve
un ID de asiento válido. Bóveda rechaza días no contables antes de numerar.

Registrar en las issues de cada módulo las siguientes tareas:

- **Ventanilla y Transacciones.** Proveer el adaptador financiero de CAJ-09,
  CAJ-11 y TRX-03 con sus identificadores y reglas de comisión. Contabilidad
  debe confirmar la matriz de retiro y reverso y los auxiliares por
  subproducto para el depósito. Compartir la conexión del movimiento,
  efectivo, comisión y asiento. Probar depósito, retiro y reverso reales,
  duplicados y rollback ante fallo contable.
- **ATM.** Implementar la operación de dotación que consume `DOT_ATM` y las
  confirmaciones financieras de retiro, transferencia y reverso. El equipo
  debe definir dispensación, conciliación, matriz, comisiones y cuentas por
  subproducto con Contabilidad. Mantener la mutación SQL y el asiento en una
  transacción, con control idempotente de la confirmación y vínculo al
  original en reversos. Probar confirmación, repetición, reverso y compensación
  ante fallo o dispensación incierta en el entorno del canal.
- **Crédito.** Proveer desembolso, cobro y reverso. Acordar con Contabilidad
  la matriz y cuentas por producto o subproducto para principal, intereses,
  mora y cargos aplicables. Usar la transacción de negocio para registrar
  asiento y movimientos del crédito y definir claves estables de reintento.
  Probar desembolsos y pagos reales, sus reversos, duplicados y rollback.

**Decisión de cierre.** Con los criterios actuales, #434 sigue abierto.
Podría cerrarse como entrega del motor únicamente si los responsables
acuerdan explícitamente el reparto de alcance y registran las integraciones
pendientes en sus issues, con responsables y evidencia de aceptación propia.

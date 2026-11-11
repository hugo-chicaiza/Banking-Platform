# ATM-08 (#143): reversos ATM, implementación parcial

El endpoint permanece deshabilitado con `501 OPERACION_NO_HABILITADA`, incluso
si se configuran las dependencias genéricas de Transacciones. Exige HTTPS,
credencial del terminal y sesión operativa vigente con revocación y `pinVersion`.
No acepta sesiones expiradas, revocadas, restringidas o con PIN desactualizado.

Solo recibe `idTransaccion` y `motivo`, según la HU #143. La lectura manual acota
el cuerpo y rechaza campos desconocidos, JSON duplicado y parámetros de consulta.
No hay comprobante ficticio ni camino HTTP exitoso. No abre CooperativaDB ni
invoca escritores, movimientos, comisiones, asientos o ajustes de gavetas.

## Preparación reutilizable

La prevalidación interna reutiliza `obtener_transaccion(..., bloquear=True)`,
`existe_reverso` y `movimientos_de_transaccion` de TRX-03, además de los controles
ATM existentes. Valida la cuenta autorizada y su vinculación actual con la
tarjeta, el terminal actual, la sesión y la elegibilidad Normal/Completada.
Detecta originales Reversada o con reverso asociado y rechaza operaciones sin
movimientos, como TRX-03. Siempre hace rollback; no está conectada a la ruta.

No se exige que la tarjeta o terminal originales sean los actuales: ese alcance
no está definido en la HU, que exige la misma cuenta. Antes de habilitar el flujo
deben aprobarse las reglas sobre otros terminales y estados actuales de cuentas.

## Dependencias pendientes

- G-06 y AC-01: asiento inverso verificado y confirmación atómica de todos los
  efectos financieros. TRX-03 es un punto de referencia, no se debe llamar con un
  usuario WorkOS ficticio para ejecutar un reverso ATM.
- Efectivo: evidencia de dispensación, entrega parcial, billetes no retirados,
  devolución física y conciliación. Un motivo declarado no prueba que se deban
  aumentar gavetas ni acreditar saldos.
- Plazos, causas válidas y devolución de comisiones: decisiones pendientes de HU.
- Idempotencia: la HU exige `registroUnico` del reverso, pero no lo incluye en el
  request ni define cómo provisionarlo. No se agrega un campo o cabecera nuevo,
  ni se deriva una clave truncada. La lectura por registro está preparada; no
  garantiza replay ni comparación del motivo, que carece de persistencia definida.
- Numeración, contrato de comprobante y reconciliación de commit ambiguo deben
  resolverse antes de habilitar el endpoint. Nunca reejecutar efectos a ciegas.

La detección de un reverso por original y el índice único filtrado correspondiente
son controles diferentes de la idempotencia por registro. Deben conservarse las
restricciones existentes; esta implementación no crea índices ni migraciones.
El orden definitivo de locks debe revisarse junto al flujo financiero (TRX-03,
ATM-02, retiros y numeración) y validarse bajo concurrencia antes de habilitarlo.

## Validación local

Pruebas HTTP con JWT/credenciales sintéticos y SQL simulado. Pruebas SQL opt-in
`ATM08_LOCAL_SQL_ENABLED=1` exclusivamente en SQL Server local verificado y base
nueva sintética conservada. No utilizan Azure ni demuestran reversos financieros
completos. Los índices del laboratorio son un modelo de las restricciones
documentadas; no prueban el esquema actualmente desplegado en Azure.

Este cambio es apto únicamente para un PR parcial: ATM-08 permanece pendiente.

# ATM-03 (#142): retiros, implementación parcial

`POST /api/v1/atm/retiros` permanece cerrado con
`501 OPERACION_NO_HABILITADA`, incluso configurando dependencias genéricas de
otro módulo. Exige HTTPS, credencial del terminal y sesión operativa vigente,
incluyendo revocación, `pinVersion` y restricciones de cambio de PIN.

El request mantiene `idCuenta`, `monto`, `registroUnico` y opcionalmente
`fechaHoraDispositivo`. No recibe moneda ni exoneración: Cuentas define USD 840.
La fecha del dispositivo se normaliza con `FechaHoraEc` de Caja (sin zona se
interpreta como Ecuador) y nunca reemplaza el reloj SQL usado para autorización.
No se interpreta como evidencia
de dispensación o como parte de la identidad financiera del reintento.

## Implementado y límites

- Validación estricta, JSON acotado y sin duplicados, monto Decimal sin pérdida
  de centavos y autorización del origen dentro de la sesión.
- Prevalidación interna, desconectada de HTTP: reutiliza los locks de ATM-02,
  cuenta y tarjeta actuales, el control de PIN y el autorizador existente para
  `Retiro`. Comprueba disponible menos retenido frente a monto más comisión.
- No presume que una comisión cero constituya gratuidad aprobada: faltan enlaces
  y política de comisiones verificables antes de habilitar la confirmación.
- Lee gavetas y denominaciones sin alterarlas. Calcula una combinación exacta
  acotada por existencias, sin algoritmo greedy ni política de desgaste o mínimo
  de billetes. Excluye gavetas/denominaciones inactivas y monedas. Interpreta `A`
  según CAT-05 y la propuesta ATM-13; su validez operativa debe confirmarse con T-09.
- La regla de múltiplo usa la menor denominación de billete activa configurada,
  aunque tenga cero unidades. El cálculo limita a 100000 estados por seguridad;
  excederlo produce 503, no un falso diagnóstico de falta de efectivo.
- Toda prevalidación hace rollback. No reserva fondos, billetes o claves; debe
  repetirse dentro de la futura transacción financiera.
- La huella de `registroUnico` detecta conflictos de cuenta, tarjeta, terminal,
  canal, operación y monto. Una coincidencia solo es un candidato interno: no
  devuelve comprobantes ni afirma idempotencia financiera completa.

No hay débitos, transacciones, movimientos, comisiones, asientos ni cambios de
inventario en el endpoint. Tampoco hay simulaciones de dispensa exitosa.

## Dependencias pendientes para habilitar

1. G-06/AC-01: configuración contable aprobada y confirmación atómica de débito,
   comisión, movimiento de gaveta y asiento balanceado.
2. T-09/ATM-13/ATM-14: verificar columnas reales y reglas operativas de gavetas,
   billetes, capacidad, estados, abastecimiento y convivencia de locks.
   Las lecturas propuestas usan nombres documentados; no se verificó Azure en
   esta implementación. Una incompatibilidad SQL falla cerrada con 503.
3. Tarifario/exoneraciones T-11: nunca decididas desde sesión ATM. No se inventan
   importes ni exoneraciones.
4. Precisar códigos de procesamiento, numeración y mapeo del autorizador: `61`
   puede representar varios límites y `65` no tiene error HTTP definido en HU.
   `05` también puede cubrir restricciones de producto. La prevalidación falla
   con 501 ante estas ambigüedades; cuenta inactiva y fondos se detectan aparte.
5. Comprobante persistente, replay 200 con `Idempotent-Replay: true`, evidencia de
   denominaciones y vínculo con ATM-08. Corregir ejemplo: request 150, respuesta 40.
6. Dispensación: definir orden, identificador y protocolo del dispositivo,
   resultados parciales, efectivo no retirado, consulta de estado, conciliación y
   recuperación tras respuesta perdida o commit ambiguo. Un commit SQL no prueba
   entrega física. ATM-08 sigue parcial y no debe reponer gavetas a ciegas.

Las pruebas SQL opt-in `ATM03_LOCAL_SQL_ENABLED=1` utilizan únicamente SQL Server
local verificado, base nueva sintética conservada y un esquema mínimo. Comprueban
lecturas y locks, no compatibilidad completa de producción ni retiros reales.
Este cambio es apto únicamente para un PR parcial; ATM-03 continúa pendiente.

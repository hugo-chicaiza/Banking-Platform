# ATM-05 (#145): implementación parcial

ATM-05 permanece pendiente. Este cambio no completa ni habilita transferencias.

`POST /api/v1/atm/transferencias` exige HTTPS, credencial individual del terminal
y sesión ATM operativa, incluyendo revocación, `pinVersion` y restricciones de PIN.
Después de validar la entrada y la autorización del origen en la sesión, devuelve
`501 OPERACION_NO_HABILITADA` mediante ProblemDetails. Las solicitudes inválidas
o no autorizadas conservan sus errores de validación y seguridad.

La ruta no abre CooperativaDB, numera operaciones ni escribe transacciones,
movimientos, comisiones o asientos. Configurar las dependencias genéricas de otro
módulo tampoco habilita esta ruta: existe una barrera explícita en el servicio.

## Dependencias pendientes para habilitar operaciones

- **G-06:** matriz contable aprobada y configuración verificable para cada cuenta
  y tipo de operación, sin inventar cuentas del debe o haber.
- **AC-01:** integración que confirme débitos, créditos, comisión, movimientos y
  asiento balanceado en una única transacción, con rollback y tratamiento seguro
  del resultado ambiguo de commit.
- **Comisiones:** política y configuración aplicables, identificación del cobro
  y reglas de exoneración aprobadas. No se presupone gratuidad.
- **Códigos de procesamiento:** definir los códigos, numeración y correlación
  de las operaciones enviada y recibida con los contratos existentes.
- **Idempotencia completa:** definir las claves y vinculación del par, comprobar
  su integridad, recuperar el resultado confirmado y evitar duplicados bajo
  concurrencia y pérdida de respuesta. La huella interna actual solo detecta
  reutilizaciones incompatibles; no confirma una transferencia ni reserva claves.
- **Contrato de comprobante:** acordar respuesta, identificadores y reproducción
  en reintentos. Resolver la inconsistencia de importes del ejemplo de la HU
  (solicitud 150 frente a comprobante 25).
- Confirmar el alcance de las cuentas destino y el mapeo de restricciones y
  límites del autorizador a los errores del contrato ATM-05.

## Componentes preparatorios y validación

La prevalidación interna reutiliza las lecturas de ATM y cuentas, verifica
vinculación y estado, saldo disponible más comisión calculada por el autorizador,
y bloquea cuentas en orden determinista. Siempre revierte su transacción y no
está conectada al endpoint financiero. Sus resultados deben revalidarse dentro
de la futura transacción de confirmación; no constituyen una autorización durable.

Las pruebas HTTP locales utilizan JWT y credenciales sintéticos con SQL simulado.
Las pruebas SQL opt-in (`ATM05_LOCAL_SQL_ENABLED=1`) están limitadas al SQL Server
local verificado y crean una base nueva sintética que se conserva. Comprueban
lecturas parametrizadas y bloqueos concurrentes sobre un esquema mínimo; no
demuestran contabilización ni transferencias financieras completas. Permanecen
deshabilitadas por defecto y no utilizan Azure ni datos bancarios reales.

El PR debe presentarse como parcial y conservar la barrera financiera hasta
resolver estas dependencias y aprobar las pruebas del flujo financiero completo.

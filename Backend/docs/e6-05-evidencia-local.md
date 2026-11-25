# E6-05 · Evidencia de retenciones

Las pruebas de saldos y asientos usaron SQL Server de laboratorio y `generar_asiento`. Los casos reversibles terminaron con `ROLLBACK` y verificación de los saldos originales. Las sesiones de revisión son de laboratorio.

| Caso | Resultado observado |
|---|---|
| Retención de $60 sobre $100 disponibles | Disponible $40. El autorizador SQL rechazó un retiro de $50 con código `51`. El mayor debitó `CAPITAL` y acreditó `RESTRINGIDO` por $60. La liberación invirtió la reclasificación y el disponible volvió a $100. |
| Autoaprobación | La cola devolvió `403 APROBADOR_ES_SOLICITANTE`. La aprobación por otra persona ejecutó la solicitud y guardó la evidencia en la bandeja de auditoría. |
| Vencimiento | La tarea `CTA_LIBERAR_RETENCIONES` liberó la retención al alcanzar su fecha contable y registró el asiento espejo. |
| Interrupción | Un corte de prueba tras la confirmación de CooperativaDB dejó la solicitud aprobada. La recuperación encontró el comprobante y cerró la solicitud sin repetir retención, movimiento ni asiento. |
| Saldo reducido después de solicitar | La cola devolvió `409 SOLICITUD_DESACTUALIZADA` antes del asiento. Una retención administrativa superior al disponible se rechazó con `409 SALDO_INSUFICIENTE`. |
| Origen módulo | El intento manual devolvió `409 RETENCION_DE_MODULO`. |
| Orden judicial de $150 con $100 disponibles | Se retuvieron $100, la cuenta quedó bloqueada con disponible $0 y el motor registró la reclasificación de $100 en la misma transacción. Asiento temporal `1906` y saldos restablecidos tras la reversión. |
| Fallo contable | El motor rechazó un período cerrado. `409 CONTABILIZACION_RETENCION_RECHAZADA` y sin cambios en la cuenta, la retención ni el mayor. |
| Control de cierre | Una diferencia temporal de $1 apareció en `Cuentas.vw_RetenidoDescuadrado`. El procedimiento existente `Contabilidad.usp_ValidarCierreDiario` bloqueó con código `57651`. Se ensayó aplicar dos veces y revertir la modificación, conservando el procedimiento previo. |

## Consultas de comprobación

Ejecutar en una base de laboratorio con `@cuenta` e `@asiento` del caso de prueba.

```sql
SELECT Saldo, SaldoRetenido, Saldo - SaldoRetenido AS Disponible
FROM Cuentas.Cuenta WHERE IdCuenta = @cuenta;

SELECT Estado, MontoSolicitado, Monto, IdAsiento, IdAsientoLiberacion
FROM Cuentas.Retencion WHERE IdCuenta = @cuenta;

SELECT m.TipoMovimiento, cc.CodigoCuenta, m.Monto
FROM Contabilidad.MovimientosContables m
JOIN Contabilidad.CuentasContables cc ON cc.IdCuentaContable = m.IdCuentaContable
WHERE m.IdAsientoContable = @asiento;

SELECT IdCuenta, SaldoRetenido, SumaRetenciones
FROM Cuentas.vw_RetenidoDescuadrado WHERE IdCuenta = @cuenta;
```

## Configuración y alcance

- La copia restaurada de CooperativaDB ya tiene `CUENTAS_RETENCION` y `CUENTAS_LIBERACION` de E4-01 con componente `PRINCIPAL` y roles correctos. La migración comprueba su matriz y el servicio resuelve los auxiliares con prioridad de subproducto, producto y tipo. La semilla de `tests/sql` sirve para laboratorios antiguos sin esas plantillas.
- Para las cuentas históricas cuyo subproducto cambió con una retención activa, la liberación devuelve el monto desde el `RESTRINGIDO` del asiento original al `CAPITAL` vigente del nuevo subproducto. Si el subproducto permanece, usa el espejo exacto de los auxiliares originales. Los cambios nuevos requieren que la retención ya esté liberada.
- E4-06 (#384) agrega el cierre diario integral. Se encontró su validador SQL legado, pero no un orquestador de cierre diario en `develop`, sus ramas identificables ni la base local. E6-05 conecta el control al procedimiento disponible y lo verifica además en la tarea diaria. Al incorporar el orquestador, su recorrido deberá comprobar que un descalce también detiene el cierre integral.
- La validación del permiso `cta-retencion` se hizo con sesiones locales, incluida una sesión de `CUMPLIMIENTO`. La asignación real del rol y del permiso corresponde al tenant de WorkOS.

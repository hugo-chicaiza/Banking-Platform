# E6-04 · Evidencia de laboratorio

- SQL Server local, con `Transacciones.usp_AutorizarOperacion` mediante el repositorio compartido. Cuenta bloqueada: depósito `00`, retiro `05`. Cliente bloqueado con cuenta activa: retiro `05` y el estado de la cuenta sigue activo.
- Cuenta inactiva: se autorizó un depósito de $100, se aplicó el movimiento con `Cuentas.usp_AplicarMovimientoCuenta` y se generó el asiento balanceado 1901. La cuenta siguió inactiva. El rollback restauró los saldos y retiró la transacción y el asiento de prueba.
- Con un crédito de interés y un débito de comisión insertados por el procedimiento de movimientos en el laboratorio, ambos movimientos quedaron registrados sin modificar `FechaUltimoMovimientoCliente`. La tarea aplicó la inactivación y una segunda ejecución modificó cero cuentas. Se revirtió el ensayo completo.
- Cola local: el solicitante recibió `403 APROBADOR_ES_SOLICITANTE`; un segundo supervisor ejecutó la solicitud 19. La reactivación por asesor conservó el motivo y el tipo de documento verificado.
- Chrome con sesión de Cumplimiento: el formulario cargó el catálogo, el `PATCH` devolvió 200, la ficha quedó bloqueada y la acción de desbloqueo quedó reservada al supervisor.
- SQL Server verificó que el bloqueo y la reactivación dejaron intactos los saldos y la cantidad de asientos. Repetir un bloqueo devolvió `409 TRANSICION_INVALIDA`.
- Las migraciones de CooperativaDB y SeguridadDB se aplicaron dos veces, se revirtieron y se reaplicaron dentro de una transacción local. El ensayo de ambas bases terminó con rollback.

Consultas de comprobación (IDs exclusivamente del entorno de prueba):

```sql
SELECT Estado, Saldo, SaldoRetenido, FechaUltimoMovimientoCliente
FROM Cuentas.Cuenta WHERE IdCuenta = @Cuenta;

SELECT TipoEvento, EstadoAnterior, EstadoActual, FechaEvento
FROM Cuentas.CuentaEvento WHERE IdCuenta = @Cuenta ORDER BY IdCuentaEvento;

SELECT g.CodigoCuenta, m.TipoMovimiento, m.Monto
FROM Contabilidad.MovimientosContables m
JOIN Contabilidad.CuentasContables g ON g.IdCuentaContable = m.IdCuentaContable
WHERE m.IdAsientoContable = @Asiento;
```

Pendiente externo: comprobar el flujo completo del depósito desde Caja en E7-03 (#60), que depende de E7-01 (#401). En develop, `dependencias_operacion()` todavía devuelve `DependenciasNoConfiguradas`. Los servicios reales de cuenta, autorización, movimiento y contabilidad se verificaron directamente.

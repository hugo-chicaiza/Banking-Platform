# E6-04 · Evidencia de laboratorio

- SQL Server local, con `Transacciones.usp_AutorizarOperacion` mediante el repositorio compartido. Cuenta bloqueada: depósito `00`, retiro `05`. Cliente bloqueado con cuenta activa: retiro `05` y el estado de la cuenta sigue activo.
- Cuenta inactiva: se autorizó un depósito de $100, se aplicó el movimiento con `Cuentas.usp_AplicarMovimientoCuenta` y se generó el asiento balanceado 1901. La cuenta siguió inactiva. El rollback restauró los saldos y retiró la transacción y el asiento de prueba.
- Con un crédito de interés y un débito de comisión insertados por el procedimiento de movimientos en el laboratorio, ambos movimientos quedaron registrados sin modificar `FechaUltimoMovimientoCliente`. La tarea aplicó la inactivación y una segunda ejecución modificó cero cuentas. Se revirtió el ensayo completo.
- Cola local: el solicitante recibió `403 APROBADOR_ES_SOLICITANTE`; un segundo supervisor ejecutó la solicitud 19. La reactivación por asesor conservó el motivo y el tipo de documento verificado.
- Para reproducir las consultas, verificar `Cuentas.Cuenta.Estado`, `Saldo`, `SaldoRetenido` y `FechaUltimoMovimientoCliente`, y consultar `Cuentas.CuentaEvento` por la cuenta de prueba. Para el depósito, unir `Contabilidad.MovimientosContables` con `Contabilidad.CuentasContables` por `IdCuentaContable` dentro de la misma transacción.

Pendiente externo: comprobar el flujo completo del depósito desde Caja en E7-03 (#60), que depende de E7-01 (#401). En develop, `dependencias_operacion()` todavía devuelve `DependenciasNoConfiguradas`. Los servicios reales de cuenta, autorización, movimiento y contabilidad se verificaron directamente.

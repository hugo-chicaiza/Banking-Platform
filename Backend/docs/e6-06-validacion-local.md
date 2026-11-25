# E6-06 · Evidencia local del cambio de subproducto

Pruebas ejecutadas con SQL Server local y datos ficticios. El motor de asientos y la cola de aprobación fueron los servicios del repositorio. Las sesiones de asesor y supervisor usaron identidades de laboratorio.

## Criterios de aceptación

| Caso | Resultado |
| --- | --- |
| Titular de 18 años, cambio de ahorro de menores a ahorro para adultos | La solicitud 18 quedó ejecutada. La cuenta conservó número y USD 125,00, cambió de subproducto y el tutor quedó con fecha de fin. El asiento 1889 registró USD 125,00 al debe del CAPITAL de origen y al haber del CAPITAL de destino. Volver a ejecutar la solicitud no creó un segundo asiento. |
| Seleccionar un producto de otro tipo | La solicitud se rechazó con HTTP 422 y código `SUBPRODUCTO_NO_COMPATIBLE`. |
| Seleccionar un destino de adultos para un titular menor de 18 años | HTTP 422 y código `SUBPRODUCTO_NO_ELEGIBLE`. |
| Consultar y autorizar operaciones después del cambio | El servicio de condiciones devolvió saldo mínimo de USD 2,00 antes y USD 9,00 después. El techo por operación de ventanilla bajó de USD 100,00 a USD 50,00. El procedimiento real autorizó el retiro de USD 60,00 antes (`00`) y lo rechazó después (`61`). El depósito de USD 10,00 pasó de `00` a `05` al aplicar el nuevo saldo máximo de USD 130,00. La prueba se revirtió. |
| Permisos y separación de funciones | El supervisor sin rol asesor no pudo solicitar. La autoaprobación devolvió HTTP 403 y `APROBADOR_ES_SOLICITANTE` aunque el solicitante portaba el permiso de aprobación. La cuenta quedó intacta. |
| Fallo contable | Con el periodo contable cerrado, el motor rechazó el asiento y se verificó la reversión del cambio, del fin del tutor, del evento y del mayor. |
| Dos subproductos con el mismo CAPITAL | Ambos heredaron el mismo auxiliar de su producto. Cambió el subproducto y quedó un evento, con el mismo saldo del auxiliar y sin asiento de traslado. Si Contabilidad requiere un comprobante adicional para estos casos, falta acordar su naturaleza y propósito. |
| Comparación visual | Chrome mostró las fichas de origen y destino, la acción de solicitar aprobación y la bandeja de supervisor. |

## Cuenta con retención activa

Prueba conjunta con E6-05 sobre un saldo ficticio de USD 125,00. Se retuvieron USD 60,00 y la reclasificación trasladó los USD 65,00 de CAPITAL disponible. La retención siguió respaldada por el auxiliar RESTRINGIDO que recibió el crédito original.

Al liberar, el asiento debitó USD 60,00 del auxiliar histórico y acreditó USD 60,00 al CAPITAL vigente de la cuenta. La reclasificación y la liberación se verificaron con los asientos locales 1895 y 1896. El disponible final fue USD 125,00, el retenido quedó en cero y el CAPITAL del destino recibió en total USD 125,00. La prueba se realizó dentro de una transacción reversible.

E6-06 exige que el importe retenido concilie con las retenciones activas respaldadas por asientos contabilizados. Un saldo retenido sin respaldo deja la cuenta sin cambios y devuelve `RETENCION_SIN_RESPALDO_CONTABLE`.

## Consulta reproducible de asientos de prueba

```sql
DECLARE @id int = <identificador_del_asiento_local>;
SELECT a.IdAsientoContable, a.Estado, gl.CodigoCuenta, m.TipoMovimiento, m.Monto
FROM Contabilidad.AsientoContable AS a
JOIN Contabilidad.MovimientosContables AS m
  ON m.IdAsientoContable = a.IdAsientoContable
JOIN Contabilidad.CuentasContables AS gl
  ON gl.IdCuentaContable = m.IdCuentaContable
WHERE a.IdAsientoContable = @id
ORDER BY m.TipoMovimiento DESC;
```

Las cuentas contables se resuelven por rol y vigencia. La plantilla E4-01 encontrada en una copia restaurada ya tenía líneas de CAPITAL y líneas opcionales de RESTRINGIDO. E6-06 utiliza su componente `PRINCIPAL` para los fondos libres e informa `RETENIDO=0` para conservar el auxiliar histórico hasta la liberación.

Las semillas de CooperativaDB y SeguridadDB se ensayaron dos veces y se revirtieron dos veces en copias locales. Se conservaron las filas preexistentes de E4-01 y se retiró únicamente la configuración de E6-06 introducida en el ensayo.

## Integración externa pendiente

El código de `develop` en `35d33f4` y los nombres de ramas remotas consultados carecían del marcador `CLI_MAYORIA_EDAD`. La consulta del catálogo de tareas de SQL Server local devolvió cero filas para ese código. El recorrido manual aplica el cálculo vigente por fecha de nacimiento y el parámetro `CLI_EDAD_MAYORIA`. Cuando E5-09 publique la tarea, queda verificar que el marcador se emite y se utiliza en el recorrido del asesor. [Contrato de E5-09 #390](https://github.com/hugo-chicaiza/Banking-Platform/issues/390)

La aprobación de producción requiere que WorkOS entregue efectivamente `cuentas:aprobar` al supervisor. El permiso y la separación de actores se verificaron con identidades de laboratorio. La conexión de Caja de E7-01 queda fuera de estas pruebas. Los cupos y restricciones del destino se verificaron directamente con el autorizador real.

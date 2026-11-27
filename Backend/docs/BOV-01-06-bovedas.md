# Bóvedas BOV-01 a BOV-06

Las rutas gestionan las existencias, movimientos, remesas y arqueos de bóveda.
El prefijo de la API es `/api/v1/boveda`. El contrato ejecutable se genera en
`/api/openapi.json` cuando el entorno expone la documentación.

| ID | Método y ruta | Roles |
|---|---|---|
| BOV01 | GET `/bovedas` | CAJERO, SUPERVISOR, CONTADOR, ADMIN |
| BOV02 | GET `/bovedas/{idBoveda}` | CAJERO, SUPERVISOR, CONTADOR, ADMIN |
| BOV03 | GET `/bovedas/{idBoveda}/movimientos` | SUPERVISOR, CONTADOR, AUDITOR, ADMIN |
| BOV04 legado | POST `/bovedas/{idBoveda}/movimientos` | SUPERVISOR, ADMIN |
| BOV05 | POST `/bovedas/{idBoveda}/arqueos` | SUPERVISOR |
| BOV06 legado | POST `/arqueos/{idArqueoBoveda}/aprobacion` | SUPERVISOR, ADMIN |
| Historial | GET `/bovedas/{idBoveda}/arqueos` | SUPERVISOR, CONTADOR, AUDITOR, ADMIN |
| Resolver faltante | POST `/arqueos/{idArqueoBoveda}/resolucion-novedad` | SUPERVISOR |

Las rutas usan sesión WorkOS, protección CSRF, ProblemDetails y auditoría de
éxitos y fallos. Las respuestas llevan `Cache-Control: no-store`. BOV05 y la
resolución de novedades exigen que la agencia operativa del jefe coincida con
la bóveda. La API de Contabilidad y la bitácora de Auditoría exigen una sesión
con agencia operativa de tipo `Matriz` y los permisos de cada operación.

BOV01 filtra por `idAgencia` y `tipo`. BOV02 devuelve el saldo y el total de
denominaciones. BOV03 filtra por `tipoMovimiento`, `desde`, `hasta`,
`page`, `pageSize` y `sort`. El orden desempata por ID. Cada movimiento
incluye el desglose y, cuando corresponde, `idAsientoContable`.

## Movimientos

El POST directo de BOV04 devuelve 410. Las solicitudes tienen autorización
y confirmación física por etapa. El [contrato de solicitudes y autorización](BOV-04-solicitudes-autorizacion.md)
describe quién puede actuar, las reservas y el registro contable de las remesas.

## Arqueos

El Jefe de Agencia registra y cierra el conteo en un solo POST. El cuerpo
incluye `tipoArqueo` (`Programado` o `Sorpresivo`), `desglose`,
`observaciones` opcional e `idUsuarioResponsable` cuando hay faltante.
Las denominaciones omitidas cuentan como cero. Una lista vacía representa
una bóveda sin efectivo contado. El servidor guarda el inventario teórico, el
conteo real, los valores por denominación y el último movimiento previo.

La diferencia es saldo físico menos saldo teórico. El cierre registra
`CUADRADO`, `FALTANTE` o `SOBRANTE`. Si cambió la composición del efectivo,
se registran los ajustes por denominación. Si el importe neto cambió, se crea
un asiento por la diferencia neta y se vincula a los ajustes. Si el importe
neto queda en cero, los movimientos reflejan el cambio de piezas. El cierre,
el inventario, el saldo, el asiento y la auditoría se confirman en una sola
transacción.

- **Faltante.** El jefe identifica a un cajero vigente de esa agencia. La cuenta
  por cobrar y la novedad quedan vinculadas al arqueo y al responsable. El
  vencimiento se fija a las 48 horas del cierre. La novedad pasa de
  `PENDIENTE` a `VENCIDA` al consultar después del plazo y a `RESUELTA`
  cuando se confirma su resolución.
- **Sobrante.** El efectivo contado se incorpora al inventario de la bóveda
  contra la cuenta pasiva Sobrantes de Caja por Regularizar, para su análisis
  posterior.

El historial acepta `desde` y `hasta` en fechas de Ecuador inclusivas,
`tipoArqueo`, `estado`, `page` y `pageSize` (máximo 100). Ordena por
`fechaHoraArqueo` e ID descendentes. Cada item incluye los importes teórico y
físico, la diferencia, los IDs de ajuste y la novedad de cajero cuando existe.
Los registros históricos pueden aparecer con estado `REGISTRADO`, `APROBADO`
o `ANULADO`, con su testigo original y sin saldos de referencia si estos no se
guardaron. BOV06 permite terminar un arqueo histórico `REGISTRADO` cuando su
referencia sigue vigente y el aprobador difiere del arqueador.

### Resolución de una novedad

El jefe de la misma agencia registra `tipoResolucion` y `observaciones`.

| Método | Evidencia | Resultado |
|---|---|---|
| `JUSTIFICACION` | `referenciaResolucion` del documento autorizado | Compensa la cuenta por cobrar contra la cuenta de regularización |
| `REPOSICION` | `desglose` positivo por el importe exacto del faltante | Ingresa el efectivo en bóveda y compensa la cuenta por cobrar |
| `DESCUENTO_ROL` | `referenciaResolucion` del descuento aplicado en el rol | Compensa la cuenta por cobrar contra nómina por pagar |

El sistema verifica que la cuenta por cobrar sea la misma del asiento de
apertura. El descuento se acredita con la referencia del rol aplicado. La
respuesta devuelve el arqueo y la novedad con el actor, fecha, método, asiento
y movimiento de reposición cuando corresponde. La segunda resolución devuelve
409.

## Migraciones en SQL Server Management Studio

Seleccionar **CooperativaDB**, activar **Query → SQLCMD Mode** y ejecutar en
este orden. Cada script necesita una sesión que procese `GO` y detenga
errores. Colocar `:ON ERROR EXIT` al comienzo de la ventana de ejecución.

1. `migrations/20261114_boveda_bov01_06.tsql`, si falta.
2. `migrations/20261117_boveda_solicitudes_autorizacion.tsql`, si falta.
3. `migrations/20261127_boveda_movimientos_confirmacion.tsql`.
4. `migrations/20261127_boveda_reservas_operativas.tsql`.
5. `migrations/20261127_boveda_arqueos_novedades.tsql`.

Después, abrir la conexión a **SeguridadDB** y ejecutar
`migrations/seguridad/202611271900_boveda_eventos.up.sql` en la misma ventana
que confirma el destino con la siguiente sentencia.

```sql
EXEC sys.sp_set_session_context @key=N'migration_database', @value=N'SeguridadDB';
GO
```

Antes de habilitar el flujo, configurar las cuentas activas, imputables y
distintas, los tipos automáticos de asiento y el calendario contable para
cada agencia. En `Contabilidad.PlantillaBoveda`, utilizar estas familias para
arqueos o sus equivalentes versionadas.

| Tipo | Naturaleza | Debe | Haber |
|---|---|---|---|
| `AjusteFaltante` | E | Cuenta por cobrar cajero | Efectivo bóveda |
| `AjusteSobrante` | I | Efectivo bóveda | Sobrantes por regularizar |
| `ReposicionFaltante` | I | Efectivo bóveda | Cuenta por cobrar cajero |
| `JustificaFaltante` | E | Regularización de faltante | Cuenta por cobrar cajero |
| `DescuentoFaltante` | E | Nómina por pagar | Cuenta por cobrar cajero |

La cuenta por cobrar usa un código de activo. Las cuentas de sobrantes por
regularizar y nómina por pagar usan códigos de pasivo. La operación que
requiere asiento devuelve 409 y revierte los cambios si falta una plantilla
válida o el período contable está cerrado. La configuración para traslados,
provisiones y excedentes está en la [guía BOV-04](BOV-04-solicitudes-autorizacion.md).

## Validación

Las pruebas HTTP ejercitan permisos, agencia, estados, diferencias por
denominación, asientos, vencimiento, resolución y rollback. El laboratorio
opcional de SQL Server utiliza una base temporal ficticia y elimina la base
al finalizar. Ejecutar desde la raíz del repositorio.

```powershell
Backend/.venv/Scripts/python.exe -m pytest Backend/tests/unit/test_boveda_api.py Backend/tests/unit/test_boveda_arqueos_listado.py Backend/tests/unit/test_boveda_contabilidad.py Backend/tests/unit/test_autorizacion.py
$env:BOV_LOCAL_SQL='1'
Backend/.venv/Scripts/python.exe -m pytest Backend/tests/integration/test_boveda_sqlserver.py -p no:cacheprovider
Remove-Item Env:BOV_LOCAL_SQL
```

En Windows se puede usar la instancia local `MSSQLLocalDB` con ODBC 18
activando también `BOV_LOCAL_SQL_LOCALDB=1` durante esta prueba.

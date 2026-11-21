# Bóvedas: BOV-01 a BOV-06

Las rutas gestionan el efectivo de bóvedas existentes: consultas, movimientos
con doble custodia y arqueos con aprobación. Caja conserva sus dotaciones y
devoluciones. No se añaden los siete endpoints de administración y consulta
discutidos como ampliación.

## API

Prefijo: `/api/v1/boveda`. El contrato ejecutable se genera en
`/api/openapi.json` (fuera de producción); el repositorio no contiene el
`openapi.yaml` mencionado por los subissues.

| ID | Método y ruta | Roles |
|---|---|---|
| BOV01 | GET `/bovedas` | SUPERVISOR, CONTADOR, ADMIN |
| BOV02 | GET `/bovedas/{idBoveda}` | SUPERVISOR, CONTADOR, ADMIN |
| BOV03 | GET `/bovedas/{idBoveda}/movimientos` | SUPERVISOR, CONTADOR, AUDITOR, ADMIN |
| BOV04 legado (410) | POST `/bovedas/{idBoveda}/movimientos` | SUPERVISOR, ADMIN |
| BOV05 | POST `/bovedas/{idBoveda}/arqueos` | SUPERVISOR, AUDITOR, ADMIN |
| BOV06 | POST `/arqueos/{idArqueoBoveda}/aprobacion` | SUPERVISOR, ADMIN |
| Listado de arqueos | GET `/bovedas/{idBoveda}/arqueos` | SUPERVISOR, CONTADOR, AUDITOR, ADMIN |

Se reutilizan sesión WorkOS, CSRF, ProblemDetails y auditoría de éxitos/fallos.
Las respuestas no se almacenan en caché. Supervisor consulta su agencia; contador,
auditor y administrador pueden consultar otras según los roles de cada ruta.
Los movimientos y aprobaciones exigen la agencia del supervisor incluso si tiene
además otro rol global. Un auditor puede registrar un arqueo en otra agencia.

ADMIN dispone de todas las rutas del módulo. Las consultas tienen alcance global;
las solicitudes y aprobaciones mantienen el alcance de escritura de la agencia
asignada al usuario. ADMIN también debe respetar las identidades distintas para
aprobar y la cancelación exclusiva del solicitante. El testigo de un arqueo puede
ser un SUPERVISOR o ADMIN de la agencia, o un AUDITOR con alcance global.

Las escrituras de bóveda se autorizan por rol (no hay un permiso de WorkOS propio);
ver `core/security/permisos.py`. No se requiere migración SQL para este acceso.

BOV01 filtra por `idAgencia` y `tipo`. BOV02 incluye `saldoActual`, inventario,
valor/subtotal por denominación y `totalDesglose`. BOV03 filtra por
`tipoMovimiento`, `desde`, `hasta` (días inclusivos), `page`, `pageSize` (1..100) y
`sort=campo,asc|desc`. Campos: `idMovimiento`, `fechaMovimiento`, `tipoMovimiento`,
`naturaleza`, `monto`. El orden desempata por id; cada movimiento publica desglose
e `idAsientoContable`, nullable para operaciones históricas y de otros módulos.

### Movimiento

BOV-04 ahora utiliza solicitudes y una segunda sesión para aprobar y ejecutar.
El POST directo a `/bovedas/{idBoveda}/movimientos` está obsoleto y responde 410.
Contrato completo, migración y guía para clientes en
[BOV-04 solicitudes y autorización](BOV-04-solicitudes-autorizacion.md).

### Arqueo y aprobación

`GET /api/v1/boveda/bovedas/{idBoveda}/arqueos` devuelve el historial paginado
de la bóveda, incluyendo las inactivas. SUPERVISOR consulta únicamente su agencia;
CONTADOR, AUDITOR y ADMIN tienen alcance global de lectura. Bóveda inexistente
responde 404; acceso a otra agencia sin alcance global responde 403.

Filtros opcionales combinables: `desde`, `hasta` (fechas de Ecuador, días inclusivos),
`estado` (REGISTRADO, APROBADO, ANULADO), `tipoArqueo` (Programado, Sorpresivo).
`page` inicia en 1 y `pageSize` por defecto es 20, con máximo 100. El orden es
`fechaHoraArqueo` descendente y, para fechas iguales, `idArqueoBoveda` descendente.
Se rechazan fechas invertidas, anteriores a 1753, `hasta=9999-12-31`, parámetros
desconocidos/repetidos y valores fuera de los tipos/rangos documentados.

```http
GET /api/v1/boveda/bovedas/1/arqueos?desde=2026-11-01&hasta=2026-11-17&estado=REGISTRADO&page=1&pageSize=20
```

La respuesta tiene `{items, page, pageSize, total}`. Cada item es una cabecera con
id y fecha del arqueo, bóveda, tipo, estado, arqueador, testigo, observaciones,
saldoTeorico, saldoFisico, diferencia (físico menos teórico), aprobador/fecha de
aprobación e identificadores de sus movimientos de ajuste. Los saldos y la
diferencia pueden ser null en registros anteriores a la migración de referencia;
no se completan con el saldo actual. El listado no incorpora el detalle de piezas
por denominación. Una página fuera de rango devuelve `items: []` y conserva total.
No modifica efectivo ni estados y no requiere una migración SQL adicional; utiliza
las tablas y columnas de las migraciones existentes de bóvedas.

BOV05 recibe `tipoArqueo` (Programado/Sorpresivo), `idUsuarioTestigo`, `desglose`
y `observaciones`. El arqueador proviene de la sesión. El testigo debe ser distinto,
activo, vinculado, sin bloqueo y SUPERVISOR o ADMIN de esa agencia, o AUDITOR.

Se guarda conteo, cantidades esperadas, valores unitarios, saldo esperado/físico y
último movimiento al registrar. Denominaciones omitidas se cuentan como cero;
se permite cero en el conteo y se incluyen las existencias esperadas omitidas.
El saldo no cambia durante el registro. La diferencia siempre es contada menos
esperada. Durante el conteo físico debe coordinarse la suspensión operativa: el
bloqueo de BD solo protege la petición de registro, no toda la actividad humana.

BOV06 no requiere body. Solo aprueba REGISTRADO y el aprobador debe ser distinto
del arqueador. Puede coincidir con el testigo, como permiten las reglas actuales.
Se rechaza si hubo movimientos posteriores o cambió el inventario/valor de
referencia; se debe registrar un nuevo arqueo. No se aprueban arqueos anteriores a
la migración que carezcan de referencia verificable.

Un arqueo puede generar un ajuste de faltante y otro de sobrante, incluso con
diferencia monetaria neta cero. Se actualizan las piezas exactas y se generan los
asientos de cada movimiento. `idMovimientoAjuste` conserva el primer ajuste por
compatibilidad; `idsMovimientosAjuste` devuelve todos. La referencia inversa está
en `MovimientoBoveda.IdArqueoBoveda`. Se conserva arqueador como iniciador de los
movimientos de regularización y aprobador como autorizador; la aprobación guarda
su autor y fecha. Otra aprobación responde 409 y no duplica los ajustes.

## Base de datos y configuración previa al despliegue

Aplicar `migrations/20261114_boveda_bov01_06.tsql` sobre CooperativaDB con un
ejecutor que soporte GO y detenga la ejecución ante errores (`sqlcmd -b`). La
migración está preparada para repetirse y conserva los datos existentes.
No fue aplicada a bases de negocio por esta implementación.

La extensión `.tsql` identifica el dialecto de SQL Server ante SonarQube Cloud;
su configuración predeterminada interpreta `.sql` como PL/SQL de Oracle.

- Admite ProvisionExterna en los CHECK de tipo/naturaleza.
- Añade vínculo al asiento y al arqueo en MovimientoBoveda.
- Añade clave/huella de idempotencia e índices únicos.
- Guarda referencia histórica, aprobador y fecha en arqueos.
- Permite hasta un movimiento por naturaleza y arqueo para regularizaciones mixtas.
- Añade `Contabilidad.PlantillaBoveda`, sin insertar configuraciones ficticias.

El contador debe configurar una fila por agencia/tipo/naturaleza, con
`IdCuentaDebito`, `IdCuentaCredito`, `IdTipoAsiento`. Combinaciones:

| Tipo | Naturaleza |
|---|---|
| ProvisionExterna | I |
| EnvioExcedente | E |
| Traslado | E e I |
| AjusteFaltante | E |
| AjusteSobrante | I |

Las cuentas deben ser distintas, activas e imputables; el tipo de asiento debe
estar activo y el período contable ABIERTO. No hay números de cuenta por defecto:
el mapeo económico lo define el contador (G-06). Se usa AC-02 y los SP existentes
de numeración/contabilización. Si falta configuración, BOV04 o un BOV06 que requiera
ajustes responde 409 y **no confirma efectivo**. Un arqueo sin diferencias puede
aprobarse sin asiento. No se habilitan ni modifican las dependencias de Caja/ATM.

## Errores de negocio añadidos

Además de sesión/roles, validación 400, parámetros desconocidos/repetidos y errores
F-04 de BD:

| HTTP | Códigos |
|---|---|
| 400 | ORDEN_INVALIDO, RANGO_FECHAS_INVALIDO, FECHA_HASTA_INVALIDA |
| 403 | SIN_ACCESO_AGENCIA, AGENCIA_NO_ASIGNADA, USUARIO_NO_REGISTRADO, USUARIO_INTERNO_NO_VINCULADO |
| 404 | BOVEDA_NO_ENCONTRADA (URL), ARQUEO_NO_ENCONTRADO |
| 422 | BOVEDA_NO_ENCONTRADA (contraparte), TRASLADO_REQUIERE_CONTRAPARTE, CONTRAPARTE_INVALIDA, DENOMINACION_NO_ENCONTRADA, SALDO_INSUFICIENTE, PARTICIPANTE_NO_HABILITADO, MONTO_FUERA_RANGO, CANTIDAD_FUERA_RANGO, DESGLOSE_EXCEDE_LIMITE |
| 409 | DOBLE_CUSTODIA_VIOLADA, ARQUEADOR_IGUAL_TESTIGO, APROBADOR_IGUAL_ARQUEADOR, BOVEDA_NO_ACTIVA, BOVEDA_DESCUADRADA, DENOMINACION_NO_ACTIVA, IDEMPOTENCIA_CONFLICTO, ARQUEO_NO_REGISTRADO, ARQUEO_DESACTUALIZADO, ARQUEO_SIN_REFERENCIA, PERIODO_CONTABLE_NO_ABIERTO, PLANTILLA_BOVEDA_NO_CONFIGURADA, CUENTA_CONTABLE_NO_HABILITADA |
| 500 | CALENDARIO_SIN_FECHA |

## Validación

Pruebas HTTP con repositorio transaccional en memoria: roles, agencia, formatos,
inventario, traslados, claves repetidas, arqueos, aprobación y rollback. Pruebas de
configuración contable y participantes. La matriz global de autorización incluye
todas las rutas del módulo.

Laboratorio opcional SQL Server: fixture estructural sin datos de negocio derivado
del SQL proporcionado, migración ejecutada dos veces, cuentas y usuarios ficticios,
operaciones reales, rollback y concurrencia. Solo instancia local SQLEXPRESS,
autenticación integrada, nombre aleatorio y marca verificable; se elimina al acabar.
No lee .env para elegir el destino. Desde la raíz del repositorio, PowerShell:

```powershell
Backend/.venv/Scripts/python.exe -m pytest Backend/tests/unit/test_boveda_api.py Backend/tests/unit/test_boveda_contabilidad.py Backend/tests/unit/test_autorizacion.py
$env:BOV_LOCAL_SQL='1'
Backend/.venv/Scripts/python.exe -m pytest Backend/tests/integration/test_boveda_sqlserver.py -p no:cacheprovider
Remove-Item Env:BOV_LOCAL_SQL
```

## Ampliaciones

Crear/editar/activar bóvedas; consultar el detalle individual/anular arqueos; conciliación dedicada
o integrada en BOV02. Después: remesas en tránsito, confirmación del testigo, reversos, jornadas, custodios y monedas. Las operaciones
externas también pueden ampliarse con contraparte y comprobante estructurados.

# E1-12 #104: comisiones y exoneraciones

La estructura de exoneraciones y las versiones de tarifa tienen migraciones
separadas. Antes de habilitar las rutas, aplicar el orden SQL de este documento.

## Contrato HTTP

Prefijo completo: `/api/v1/parametros`. JSON camelCase; importes como números en
respuestas (Decimal en Python). El OpenAPI generado contiene los schemas completos.

| Método | Ruta relativa | Resultado |
|---|---|---|
| GET | `/comisiones` | 200, lista de tarifas con todas sus asociaciones y vigencias |
| POST | `/comisiones` | 201, tarifa creada y asociada, o tarifa existente asociada por ID |
| PATCH | `/comisiones/{idComision}` | 200 para metadatos o valor idéntico. 202 con `idSolicitud` para un cambio de tarifa |
| GET | `/comisiones/{idComision}/tarifa?fecha=2026-12-01` | 200 para la versión vigente en esa fecha o 404 si no existe |
| GET | `/exoneraciones?idComision=1` | 200, reglas; filtro opcional por comisión |
| POST | `/exoneraciones` | 201, regla automática con actor de creación |
| PATCH | `/exoneraciones/{idExoneracion}` | 200, actualización parcial de regla |

Las lecturas exigen sesión y roles ADMIN/SUPERVISOR/ASESOR, igual que la lectura de
administración de catálogos. Las escrituras exigen el rol **ADMIN**: no hay un permiso de
WorkOS propio para parámetros (ver `core/security/permisos.py`). `PAR-EDITAR` es la
etiqueta funcional del issue, no un permiso.

`require_auth` exige el vínculo interno activo; `UsuarioAuditoria` obtiene el
entero de la sesión y lo pasa al servicio/repositorio. El cliente **no puede enviar
RegistradoPor, CreadoPor, IdSolicitud ni identificadores de auditoría**. La asociación
guarda RegistradoPor; la regla guarda CreadoPor. Las modificaciones usan el actor
actual en la auditoría, sin sobrescribir al creador original.

### Crear una tarifa nueva

```json
{
  "codigoComision": "SERVICIO",
  "tipoComision": "Otro",
  "tipoCalculo": "Fijo",
  "valor": 0.05,
  "idCanal": 1,
  "codigoTipoTransaccion": "CODIGO_EXISTENTE",
  "descripcion": "Descripción del servicio",
  "vigenciaDesde": "2026-12-01",
  "vigenciaHasta": null,
  "idCuentaContableIngreso": null
}
```

Valores de tipoComision: Retiro, Transferencia, Consulta, Mantenimiento, Emision
Tarjeta, Reposicion Tarjeta, Otro. TipoCalculo: Fijo o Porcentaje. En Porcentaje,
valor debe estar entre 0 y 100 y se exigen montoMinimo y montoMaximo (mínimo ≤ máximo).
En Fijo esos límites se omiten o son null. Valor admite hasta cuatro decimales;
los límites monetarios admiten dos. Se valida canal/evento activo, unicidad del
código y ausencia de solape para operación/canal antes de confirmar ambas filas.
Si falla la asociación se revierte también la nueva tarifa. El código de evento
debe existir: la API no inventa un evento físico de reposición.

### Asociar una tarifa existente con el actor autenticado

Este segundo cuerpo de POST no cambia el valor de la tarifa. Permite cargar las
dos asociaciones iniciales sin escribir manualmente RegistradoPor en SSMS:

```json
{
  "idComision": 1,
  "idCanal": 2,
  "codigoTipoTransaccion": "Retiro",
  "vigenciaDesde": "2026-12-01"
}
```

Para la segunda: idComision=2, idCanal=3, codigoTipoTransaccion=Transferencia_Enviada.
La fecha del ejemplo no es una fecha de carga predeterminada: enviar la fecha
efectiva acordada, nunca una pasada. La asociación debe estar contenida en la
vigencia de la tarifa, y pertenecer al mismo canal. Repetir exactamente la misma
asociación devuelve 201 con el mismo registro; conserva el RegistradoPor original.
Un solape distinto devuelve 409, incluso si se intenta crear otra tarifa con otro
código para eludir la aprobación. Esta API **ya funciona contra SQL local** con
sesión simulada; el entorno real sigue necesitando un vínculo válido en core.

PATCH de comisión admite descripcion, estado A/I, idCuentaContableIngreso (nullable),
valor y vigenciaDesde. Omitir conserva; null solo permite limpiar la cuenta contable.
Un valor idéntico sin fecha nueva no genera solicitud ni actualiza el valor.
Un valor distinto o una nueva fecha requieren el flujo de aprobación. No se
pueden cambiar canal, código, tipo de cálculo ni límites mediante PATCH.
La cuenta contable solo valida un entero positivo: la FK y su destino siguen
pendientes; no se afirma que un ID aceptado corresponda a una cuenta contable real.

### Reglas automáticas

```json
{
  "idComision": 1,
  "idProducto": null,
  "idSubProducto": 1,
  "tipoCliente": "Natural",
  "operacionesGratisMes": 3,
  "porcentajeExonerado": 100,
  "vigenciaDesde": "2026-12-01",
  "vigenciaHasta": null,
  "estado": "A"
}
```

Producto, subproducto, tipoCliente y cupo pueden ser null. Se comprueba que el
subproducto exista y, si se envía producto, le pertenezca. Porcentaje 0–100 inclusive,
con dos decimales; cupo entero 0–32767 o null (sin límite). Estado inicial A por
defecto. No hay solicitud ni aprobación de exoneraciones.

PATCH admite estos mismos datos salvo idComision, que es inmutable. Rechaza cuerpo
vacío y null en porcentaje/estado/fecha de inicio. No se cambian datos de una regla
con inicio pasado (422 VIGENCIA_PASADA); se permite activar/desactivar su estado.
Una modificación se valida sobre la regla completa, preservando campos omitidos.
Se rechazan solapes activos para el mismo alcance. Las vigencias son `[desde,hasta)`.

`parametros.service.comision(conn,tipo,canal,cuenta,fecha,monto_operacion=...)`
selecciona las tarifas activas y las reglas vigentes según la cuenta. Prioridad:
subproducto > producto > general; dentro de ese nivel, tipo de cliente específico
> todos. No suma porcentajes. Si datos preexistentes empatan en prioridad, falla
con 409 EXONERACION_AMBIGUA. Un cupo agotado cobra la tarifa sin buscar una regla
menos específica. Porcentaje 0 no registra una exoneración aplicada.

Cuenta operaciones Normal/Completada anteriores a la fecha, del mismo mes,
cuenta, operación y canal. La tercera es gratis si hay dos previas; la cuarta
cobra. Usa el cálculo de #446 y redondea solo el importe final con ROUND_HALF_UP:
50 % de exoneración sobre 0,05 deja 0,03. Sin tarifa devuelve lista vacía y total
0 al sumar. Cada resultado conserva idComision, montoBase, montoCobrar e
idExoneracion si se aplicó. La fecha naive representa hora de Ecuador; fechas
con zona se convierten a Ecuador.

## Aprobación de tarifas

`PAR-COMISION` usa la cola E0-08 con objetivo global `Comision`. Solicita un
ADMIN. Aprueba o rechaza otra persona con `parametros:aprobar`. La cola guarda
solicitante, resolutor, versión de origen, antes, después y resultado.

El PATCH sensible debe venir separado de los metadatos. Si solo se envía valor,
la fecha propuesta es el día siguiente en Ecuador continental. Si solo se envía
fecha, la nueva versión conserva el valor de la versión que divide.
La fecha debe ser posterior al inicio de la última versión y anterior a su fin,
si tiene uno. Esta operación agrega una versión sucesora y conserva el fin
original. Una propuesta atrasada, solapada o desactualizada se rechaza.

La aprobación cierra el intervalo anterior y registra la versión nueva una sola
vez. La fecha efectiva activa el valor automáticamente. Los intervalos son
`[desde, hasta)`. El cálculo Python y `fn_CalcularComision` utilizan esa fecha.
El ID de la comisión, sus asociaciones, exoneraciones y vínculos de producto
conservan sus referencias y sus propias vigencias. El GET por fecha consulta el
historial de valores. La elegibilidad para un cobro sigue dependiendo del
estado de la comisión y las asociaciones.

### Orden SQL

1. En CooperativaDB, con el esquema de E1-12 y E0-08 instalado, confirmar
   `SESSION_CONTEXT('migration_database')` con el nombre de la base y ejecutar
   `scripts/sql/e112/004_versiones_tarifa.sql`. En instalaciones nuevas ejecutar
   `001_exoneraciones.up.sql` primero y `002_cargar_tarifas.sql` después.
2. En SeguridadDB, después del catálogo E0-08 y con esa base confirmada
   en la sesión, ejecutar `202611180805_comision_aprobacion.up.sql`.
3. Desplegar el backend después de ambos cambios SQL. Suspender las altas de
   comisión durante el cambio, porque la versión anterior del backend usa
   `OUTPUT` sin `INTO` y SQL Server lo rechaza al instalar el trigger de alta.
   Comparar el cálculo SQL
   del entorno con el de laboratorio antes de sustituir su definición, y
   revisar consumidores externos que consulten `Comisiones.Valor`.

La migración conserva cada fila e ID original y siembra un intervalo por
registro existente. Los valores históricos que ya no estaban almacenados
quedan fuera del alcance de la migración. `Comisiones.Valor` conserva el valor
inicial como parte del registro base. Para consultar la tarifa usar la tabla de
versiones o la proyección de presentación, según corresponda.

## Errores y auditoría

ProblemDetailsRoute conserva type, title, status, code, detail y traceId. Como en
el core, errores de schema/campos extra/cuerpo vacío/porcentaje/cupo inválido son
400 DATOS_INVALIDOS; referencias y reglas de negocio inválidas son 422.

| Estado | Causas relevantes |
|---|---|
| 401 / 403 | Sin sesión, sin vínculo interno, sin permiso o rol de lectura |
| 404 | COMISION_NO_ENCONTRADA o EXONERACION_NO_ENCONTRADA en PATCH |
| 409 | CODIGO_COMISION_DUPLICADO, COMISION_VIGENCIA_SOLAPADA, EXONERACION_VIGENCIA_SOLAPADA, COMISION_INACTIVA |
| 422 | VIGENCIA_PASADA, VIGENCIA_FUERA_DE_COMISION, CANAL_COMISION_INCOMPATIBLE, referencias inexistentes/incompatibles |
| 422 | CAMBIO_TARIFA_MIXTO si se envían cambios sensibles y metadatos juntos |

Las escrituras son transaccionales y bloquean la configuración para serializar
comprobaciones de unicidad/solape. Auditoría usa el mecanismo común, un evento
Exitoso/Fallido con actor real y cambios antes/después cuando procede:
PAR_COMISION_REGISTRADA y PAR_EXONERACION_EDITADA. Estos eventos conservan
el comportamiento best-effort del core. La cola registra por separado las
decisiones de aprobación, vinculadas a la versión por `IdSolicitud`.

## Alcance probado de punta a punta

Las seis rutas alcanzan sus repositorios reales en SQL Server local. Se prueban
tarifas nuevas, asociaciones de tarifas existentes, idempotencia, actor de sesión,
lecturas, PATCH de metadatos/estado, CRUD de reglas, solapes, rollback de cambios
de valor y selección/cálculo automático sobre registros reales de operaciones.
La sesión WorkOS y la escritura de auditoría se simulan; se comprueban los eventos
emitidos. No se hizo login contra WorkOS ni escritura a SeguridadDB/Azure.

El servicio de cálculo bloquea la cuenta hasta que termine la transacción de su
llamador y devuelve los importes e IDs para registrar el cobro. **No debita ni
persiste una transacción financiera por sí solo**. El autorizador SQL existente
todavía usa fn_CalcularComision sin reglas; no se alteró ese procedimiento en esta
entrega. Falta que los flujos de dinero llamen al servicio automático y registren
el IdExoneracion aplicado en su contrato de persistencia. El flujo físico de
reposición y su débito único continúan pendientes; no se afirma que una reposición
real ya cobre o exonere. No se asoció la tarifa de 5 a Cobro_Comision.

Comandos locales (con dependencias del repo instaladas):

```powershell
python -m pytest Backend/tests -q -p no:cacheprovider
$env:E112_LOCAL_SQL_ENABLED='1'
python -m pytest Backend/tests/integration/test_e112_sql_local.py Backend/tests/integration/test_parametros_sql_local.py -q -p no:cacheprovider
```

Los tests SQL usan exclusivamente shared memory local, bases temporales
E112_Test_<uuid> y datos ficticios. No leen .env para elegir su destino.

Resultado final: **3397 aprobadas, 262 omitidas y 4 advertencias** en la suite
general; **17 pruebas SQL locales aprobadas** (14 de migración/carga y tres de
API/cálculo). Las advertencias corresponden a TestClient/httpx y marcas integration
preexistentes. Una primera corrida tuvo un falso positivo en el teardown de un
test ATM: el traceId aleatorio contenía el PIN ficticio de cuatro dígitos. Ese
archivo pasó al repetirlo y la corrida completa final terminó sin errores.

### Fecha efectiva y baja de comisiones

La vigencia es diaria en la zona horaria de Ecuador continental. Si se modifica
solo el valor, se propone el día siguiente a la solicitud. Una fecha propuesta
que no sea futura devuelve `422 VIGENCIA_TARIFA_NO_FUTURA`. Al aprobar, la fecha
debe seguir siendo posterior a ese día. Si llegó o ya pasó, E0-08 registra el
intento como fallido y devuelve `409 VIGENCIA_TARIFA_VENCIDA`. Para programar
otra fecha, envíe una nueva solicitud.

El catálogo devuelve `409 COMISION_CON_HISTORIAL` al intentar borrar una comisión.
Use `PATCH /api/v1/parametros/comisiones/{idComision}` con `{"estado":"I"}`
para desactivarla y conservar sus asociaciones e historial.

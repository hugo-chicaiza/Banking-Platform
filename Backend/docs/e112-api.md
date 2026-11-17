# E1-12 #104: comisiones y exoneraciones

Implementación local en `feat/backend-104-esquema-comisiones`, actualizada desde
`origin/develop` a `9422e910b85ee1a8fc737015165952bdaf876ed5`. Se conserva la
migración separada en `scripts/sql/e112/001_exoneraciones.up.sql`. Sin ejecución en
Azure, commit ni push. Antes de usar estas rutas en una base, aplicar la estructura.

## Contrato HTTP

Prefijo completo: `/api/v1/parametros`. JSON camelCase; importes como números en
respuestas (Decimal en Python). El OpenAPI generado contiene los schemas completos.

| Método | Ruta relativa | Resultado |
|---|---|---|
| GET | `/comisiones` | 200, lista de tarifas con todas sus asociaciones y vigencias |
| POST | `/comisiones` | 201, tarifa creada y asociada, o tarifa existente asociada por ID |
| PATCH | `/comisiones/{idComision}` | 200, metadatos/estado; cambio de valor protegido con 501 mientras falte E1-10 |
| GET | `/exoneraciones?idComision=1` | 200, reglas; filtro opcional por comisión |
| POST | `/exoneraciones` | 201, regla automática con actor de creación |
| PATCH | `/exoneraciones/{idExoneracion}` | 200, actualización parcial de regla |

Las lecturas exigen sesión y roles ADMIN/SUPERVISOR/ASESOR, igual que la lectura de
administración de catálogos. Las escrituras exigen **`require_permiso("catalogos:editar")`**,
el permiso vigente para estos parámetros en `core/security/permisos.py` (asignado
inicialmente a ADMIN). `PAR-EDITAR` es la etiqueta funcional del issue; no se agregó
un slug paralelo que WorkOS aún no conoce. Un rol ADMIN sin permiso no escribe;
un usuario con el permiso puede escribir independientemente de su rol.

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
Un valor idéntico no genera solicitud ni actualiza el valor. Un valor distinto o
una nueva vigencia de valor requieren el flujo pendiente descrito abajo. No se
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

## Aprobación de valor: operación pendiente

Se revisaron #367 y el código actualizado de develop. No existe módulo/servicio
de parámetros de E0-09/E1-10 ni una cola genérica con registro de solicitudes y
manejador que active vigencias de comisiones. La aprobación de arqueos de bóveda
es de otro dominio y no se reutiliza para este cambio.

El punto exacto preparado es **`parametros.service.solicitar_cambio_valor(conn,
id_comision,cambios,actor)`**, invocado desde actualizar_comision antes de escribir.
Por ahora responde **501 APROBACION_PARAMETRO_NO_DISPONIBLE**, revierte toda la
operación (incluidos metadatos enviados junto al valor) y audita el intento. La
tarifa vigente queda intacta. El PATCH legado de administración de comisiones
también bloquea cambios de valor/vigencia para evitar un camino alternativo.

Al integrar E1-10 faltará reemplazar ese bloqueo por la llamada al servicio oficial
que persista la propuesta con actor y vigencia, y adaptar la respuesta del PATCH
a **202 con idSolicitud real**. El manejador de aprobación debe activar una nueva
vigencia conservando la historia; rechazar/cancelar no altera la tarifa vigente.
No se creó una cola paralela ni se devuelve un 202 sin solicitud persistida.
El registro inicial de una tarifa nueva responde 201; no cambia una tarifa ya
activa para el mismo evento/canal porque la comprobación de solapes lo impide.

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
| 501 | APROBACION_PARAMETRO_NO_DISPONIBLE para cambiar valor/vigencia |

Las escrituras son transaccionales y bloquean la configuración para serializar
comprobaciones de unicidad/solape. Auditoría usa el mecanismo común, un evento
Exitoso/Fallido con actor real y cambios antes/después cuando procede:
PAR_COMISION_REGISTRADA y PAR_EXONERACION_EDITADA. No se crea otro historial.
Su persistencia comparte el comportamiento best-effort del core.

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

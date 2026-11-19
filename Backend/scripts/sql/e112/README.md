# E1-12 (#104): estructura y asociaciones de comisiones

Para revisión y ejecución manual en SSMS. No se ejecutó SQL en Azure.
Rama: `feat/backend-104-esquema-comisiones`; base actualizada antes de implementar
las rutas: `9422e910b85ee1a8fc737015165952bdaf876ed5` (incluye PR #446 y #447).
Contrato de la API y límites de integración: [e112-api.md](../../../docs/e112-api.md).

## Estructura

Seleccionar expresamente la base CooperativaDB de destino en SSMS.
Ejecutar `000_inspeccionar.sql` y contrastar sus resultados antes de aplicar
`001_exoneraciones.up.sql`. La migración es transaccional y repetible:

- Agrega `Comisiones.IdCuentaContableIngreso int NULL`. La FK contable queda
  pendiente de confirmar tabla y clave de destino; no se inventa una cuenta.
- Crea `ExoneracionComision` con PK IDENTITY, FKs a comisión, producto y subproducto,
  porcentaje **0–100 inclusive**, cupo mensual NULL (sin límite) o no negativo,
  estado A/I y tipo de cliente Natural/Juridico/NULL.
- Usa vigencias `[desde,hasta)`, como el cobrador SQL local: un fin no nulo debe
  ser posterior al inicio. Reemplaza el CHECK de porcentaje del borrador >0.
- Valida datos existentes; si hay datos incompatibles, revierte y exige resolverlos.
  No elimina registros. La fecha de creación se guarda en UTC.

El script 001 instala los datos de exoneración. Después, ejecutar
`004_versiones_tarifa.sql` antes de `002_cargar_tarifas.sql` y del despliegue del
backend. El script 004 siembra las versiones y actualiza
`fn_CalcularComision` con la misma firma para que
`usp_AutorizarOperacion` lea la tarifa del día que recibe. La exoneración
automática se aplica en el cálculo Python. Su integración con los débitos
legados sigue teniendo el alcance descrito en el contrato de la API.

## Carga pendiente del ID oficial

`002_cargar_tarifas.sql` no tiene usuario por defecto y aborta sin
`SESSION_CONTEXT(N'e112.registrado_por')`. No usar un ID WorkOS, un ID arbitrario,
ni el ID ficticio del laboratorio como ID de Azure.

En la revisión previa se observó un despliegue exitoso de **backend-dev** para
`327c21a95f15e3427b3211ec4e539897f470fbab`:
[Actions 44016863293](https://github.com/hugo-chicaiza/Banking-Platform/actions/runs/44016863293).
El job «Desplegar al Web App» terminó exitosamente. Es evidencia del despliegue de
Actions, no una lectura del SHA del proceso actualmente en ejecución.
En ese commit `UsuarioAuditoria → usuario.interno() → _id_interno_db()` consulta
`SeguridadDB.Organizacion.Usuarios` (UsuarioID por KeyUsuario y Estado Activo).
`WORKOS_AUDIT_USER_IDS` solo se declara/valida en settings; el resolutor no lo usa.
El usuario informó que esa tabla ya no existe en su entorno y confirmó que
**E1-12 debe reutilizar UsuarioAuditoria**. No se modificó autenticación ni se
asumió que el mapa de configuración sustituya ese contrato. La restauración o
actualización del vínculo en core sigue pendiente; E1-12 debe fallar con el error
del resolutor si no puede resolver al actor, sin inventar un entero.

### Preferir la carga mediante el flujo autenticado

El nuevo `POST /api/v1/parametros/comisiones` permite asociar una tarifa existente
enviando idComision, idCanal, codigoTipoTransaccion y vigenciaDesde. El router recibe
`actor: UsuarioAuditoria` y la asociación guarda ese entero en RegistradoPor.
El permiso vigente es catalogos:editar. No acepta actor ni auditoría del cliente.
Se probó contra SQL local la carga de las dos asociaciones iniciales, su
idempotencia y el rechazo de un actor suplantado. Esta vía autenticada es preferible
cuando esté desplegada y el vínculo del core resuelva al usuario real. La migración
de estructura permanece separada. `002` se conserva como alternativa manual
parametrizada; no se debe ejecutar en Azure mientras falte el ID oficial.

Cuando Seguridad confirme el entero oficial, configurar en la misma conexión de
SSMS que ejecutará 002 (reemplazar NULL solo tras esa confirmación):

```sql
DECLARE @IdOficial int = NULL; -- pendiente; así la carga aborta sin escribir
EXEC sys.sp_set_session_context @key=N'e112.registrado_por', @value=@IdOficial;
EXEC sys.sp_set_session_context @key=N'e112.fecha_efectiva', @value=NULL;
EXEC sys.sp_set_session_context @key=N'e112.incluir_reposicion', @value=0;
```

Con fecha NULL se usa el día efectivo de ejecución en Ecuador, no una fecha
histórica fija. Si se acuerda una fecha explícita de carga, usar `YYYY-MM-DD` en
ese contexto y conservarla en el registro de ejecución. Al terminar, limpiar
los valores de SESSION_CONTEXT o cerrar la conexión.

La carga por defecto incluye solo:

| Evento | Canal | Comisión | Valor existente |
|---|---|---|---|
| Retiro | ATM (2) | 1 | 0,45 |

La tarifa TRF-WEB de 0,20 se conserva en el catálogo
para futuras transferencias interbancarias salientes.
No debe asociarse a Transferencia_Enviada, ya que
este evento también representa transferencias internas.

Si existe una asociación activa o futura incorrecta,
la carga aborta sin modificar ni eliminar registros.

### Diagnóstico de asociaciones WEB incorrectas

```sql
SELECT p.*, c.CodigoComision, c.Valor
FROM Transacciones.ComisionTipoTransaccion p
JOIN Transacciones.Comisiones c
    ON c.IdComision = p.IdComision
WHERE p.CodigoTipoTransaccion = 'Transferencia_Enviada'
  AND p.IdCanal = 3
  AND (c.IdComision = 2 OR c.CodigoComision = 'TRF-WEB')
  AND p.Estado = 'A'
  AND (
      p.VigenciaHasta IS NULL
      OR p.VigenciaHasta > CONVERT(date, DATEADD(hour, -5, SYSUTCDATETIME()))
  );
```


Comprueba código y estado del canal/evento, valor fijo, estado y vigencia de la
comisión; no crea ni cambia tarifas. En el laboratorio local se verificó mediante
`sys.columns` que `IdComisionTipoTransaccion` es IDENTITY y que `RegistradoPor` es
NOT NULL, sin DEFAULT. **Azure debe cotejarse con 000**. La carga omite el ID:
acepta IDENTITY o DEFAULT basado en secuencia; sin generador aborta, sin MAX+1.

El bloqueo de tabla dura hasta COMMIT y serializa cargas concurrentes. Una
asociación abierta equivalente que ya cubre la fecha se conserva, incluso al
reejecutar otro día. Duplicados existentes o cualquier otra vigencia activa que
intersecte `[fecha efectiva,infinito)` abortan toda la carga. Una vigencia que
termina exactamente ese día no solapa. No se cierran ni reescriben vigencias.
Esta protección corresponde a esta carga; no instala una restricción global
contra solapes generados por otros futuros escritores.

## Reposición física: propuesta pendiente

No se encontró un evento específico en el backend revisado. En tarjetas existe
la regeneración de PIN (`router.py` y servicio `regenerar_pin`), que
no representa reponer el plástico. El alta de tarjeta registra una solicitud y
no llama al autorizador de comisiones. En caja, el flujo común solo autoriza
comisión al retirar; las dependencias de operaciones de dinero por defecto
siguen fallando con 501. Agregar asociaciones no habilita ese flujo.

En el SQL local, `usp_AutorizarOperacion` suma `fn_CalcularComision` por código,
canal y día; verifica fondos pero no registra ni debita por sí mismo. La función
puede devolver varias comisiones si se duplican las asociaciones.

`003_propuesta_reposicion.sql` propone el evento **Reposicion_Tarjeta**, sin
principal (`Naturaleza=NULL`, `AfectaSaldo=0`), y requiere aprobación explícita
en `e112.aprobar_evento_reposicion=1`. La tarifa de 5,00 (IdComision 3, VENT 1)
solo se carga si además se habilita `e112.incluir_reposicion=1`. Estos flags son
una habilitación manual del SQL, no un indicador de que el backend esté integrado.
No ejecutar esos pasos en Azure hasta aprobar e integrar el flujo.

Para activar la tarifa en código faltaría:

1. Implementar la operación física de reposición, con identidad estable de la
   solicitud y validación de la tarjeta/cuenta, separada de regenerar PIN.
2. Emitir `Reposicion_Tarjeta` por VENT al autorizar, con la fecha efectiva y el
   monto de referencia que acuerde el contrato. El CHECK actual de Transaccion
   exige monto >0 para eventos distintos de Consulta: si se usa 5 como referencia,
   no debe aplicarse como principal además de la comisión.
3. Llamar al nuevo servicio `parametros.service.comision`, que ya selecciona la
   regla, cuenta operaciones y aplica #446. El autorizador SQL actual no devuelve IdComision ni IdExoneracion:
   completar ese contrato para registrar la regla y tarifa efectivamente aplicadas.
4. En una sola transacción, persistir la reposición y su comisión, debitar **solo
   el importe final una vez**, contabilizar y enlazar los registros. No emitir un
   segundo cargo genérico Cobro_Comision. Definir unicidad/idempotencia por la
   identidad de reposición para que reintentos y concurrencia no dupliquen el cobro.
5. Probar API + SQL: primera solicitud descuenta 5; repetida y concurrente conserva
   un cargo; fallo revierte; regenerar PIN y otra operación VENT no cobran esa tarifa.

## Pruebas locales

Con Python 3.14 y dependencias de `Backend/requirements-dev.txt` instaladas:

```powershell
$env:E112_LOCAL_SQL_ENABLED='1'
python -m pytest Backend/tests/integration/test_e112_sql_local.py -q
```

Usa autenticación Windows y shared memory `lpc:.`, sin leer .env. Crea y elimina
solo bases `E112_Test_<uuid>`. Lee la función real del laboratorio local
`CooperativaDB_ATM02_Lab`, sin modificar esa base, y la instala en la base temporal.
Las tablas de soporte son una fixture mínima con los tipos/claves relevantes
inspeccionados localmente; no es una copia ni una certificación del esquema Azure.
El usuario 900104 existe solo en la fixture ficticia y jamás debe copiarse a Azure.

Se prueba reejecución de migración/carga, límites de porcentaje/cupo, conservación
de datos, rollback por datos incompatibles, generador de ID, fecha efectiva,
conflictos históricos/futuros, duplicados, tarifa distinta y cargas concurrentes.
Para la propuesta de reposición se verifica que el cobrador devuelve una sola
fila de 5 y que otros eventos VENT devuelven 0. **No es una prueba de débito ni
del flujo completo de reposición**, que aún no está implementado.

La verificación actual incluye los 17 escenarios SQL de este script y tres
escenarios adicionales de API/repositorios/cálculo en SQL local. Los resultados
de la corrida final se entregan junto al diff. No se ejecutó una reposición con
débito real ni SQL en Azure.

### Verificación de la migración 004

Ejecute `005_verificar_versiones_solo_lectura.sql` antes y después. Use una sesión
sin transacción externa, con `migration_database` configurado con el nombre
exacto de la base, y pause las escrituras de comisiones durante el despliegue.
La instalación inicial admite la definición legada de `fn_CalcularComision`
validada en el laboratorio. La reejecución admite la propia definición versionada
de 004. Se compara desde la palabra FUNCTION y se normalizan los saltos de línea,
las tabulaciones y los espacios exteriores. Si la definición local difiere, revise la lógica antes de adaptar la
migración. El script no sobrescribe una función desconocida.

La reejecución comprueba los objetos de versionado y la cobertura de toda la
vigencia original. Cualquier falta de versión inicial, hueco, solape o
intervalo inválido aborta la transacción. Los errores 57287 a 57290 requieren
diagnosticar el estado de destino antes de volver a ejecutar.

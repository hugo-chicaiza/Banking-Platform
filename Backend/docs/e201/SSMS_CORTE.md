# Entrega vigente: estructura separada y corte atómico

Actualización 2026-11-16. El usuario confirmó que ahorro operativo en Azure ya
concilió por PN y PJ, y que `CodigoElemento` y `TipoCuenta` son calculadas.
No se consultó ni modificó Azure. Falta copiar a los parámetros los datos y la
evidencia de ese corte real; no se inventó una fecha ni un resultado de consulta.

## Dos scripts para SSMS

1. `Backend/scripts/sql/e201/001_solo_estructura.sql`: llega hasta `CK_E201_Codigo` y confirma
   únicamente las columnas/restricción. **No cambia EsImputable, saldos ni datos
   del catálogo y no crea auxiliares.** Es idempotente y tiene rollback propio.
2. `Backend/scripts/sql/e201/004_corte_completo_ssms.sql`: entregable completo,
   incluye el motor, sus dependencias y la aprobación temporal descrita abajo.
   Instalar después de 001. Su instalación no crea auxiliares ni cambia flags.
   Las llamadas están al final comentadas; las fases son preparación, aprobación
   desde otra identidad y ejecución. No ejecutar aparte el antiguo 002.

El archivo `004_corte_completo_ssms.sql` es la fuente canónica del corte y su aprobación. Las rutinas de altas/hash/motor interno no
reciben EXEC para los roles de negocio. Se retiró el DML directo del adaptador
sobre los recibos internos. Ninguna llamada cambia las columnas calculadas.

El corte completo admite únicamente `EFECTIVO_AHORRO`: no descarga ahorro ni
marca su padre a cero por accidente durante un corte parcial de efectivo.

## Qué se confirma junto

`E201.usp_EjecutarCorte` es dueño de la transacción. Dentro de ella:

1. Bloquea el recibo y revalida la autorización y los permisos actuales.
2. Compara hash del plan y versión del objetivo con lo aprobado.
3. Marca ambos padres no imputables; crea las cinco hijas en cero respetando
   51100 y heredando naturaleza, estado y valuación.
4. Resuelve sus IDs por código; registra controles, borrador, manifiesto e
   imputaciones. Llama a `usp_ContabilizarAsiento` y aplica los deltas del saldo.
5. Verifica saldos propios de origen cero y total por elemento idéntico; vincula
   recibo/asiento y consume la autorización.
6. Hace un único COMMIT externo. El COMMIT anidado del motor interno no confirma
   las altas. Un error revierte cuentas nuevas, flags, saldos, borrador, líneas y
   consumo. La autorización previa permanece disponible para un reintento válido.

Reintentar con el mismo IdSolicitud devuelve el mismo asiento sin duplicarlo.
No envolver la llamada en un BEGIN TRAN externo. Los contadores identity pueden
tener huecos tras rollback; no son cuentas ni movimientos que hayan persistido.
El campo Saldo del padre sigue siendo el subtotal del subárbol; su saldo propio
se comprueba desde movimientos, no sumando otra vez el subtotal.

## Aprobación real temporal: E0-08 NO está instalado

No se afirma validar contra una cola inexistente. 004 instala una autorización
SQL temporal, específica de este corte, con fuente verificable en la propia BD:

- `E201.IdentidadCorte`: vínculo verificado por el DBA entre un principal SQL,
  su login original y el UsuarioID del contador, habilitación y alcance institucional.
  No se da de alta automáticamente a nadie ni se confía en RolesWorkOS cacheados.
- `E201_PreparadorCorte` permite preparar; `E201_AprobadorCorte` es el permiso
  efectivo de aprobar este corte. No basta con tener el rol de contador en otro
  sistema. El DBA debe comprobar esa condición al vincular la identidad.
- El preparador se obtiene de USER_SID()/ORIGINAL_LOGIN() y el vínculo, no del
  UsuarioID enviado por el cliente. El JSON debe coincidir con esa identidad.
- `usp_AprobarCorteSSMS` obtiene al aprobador de su conexión autenticada. Exige
  otro UsuarioID, otro principal y **otro ORIGINAL_LOGIN()**. `EXECUTE AS USER`
  sobre una conexión compartida no acredita a una segunda persona y se rechaza.
- Inserta `AutorizacionSSMS` inmutable con hash, ambas identidades, fecha y comentario.
  En la misma transacción llama a `usp_RegistrarAprobacionReal`, que valida esa
  fuente y registra `ReciboReal`. No acepta un `AprobadoPor` libre ni un permiso=1.
- `usp_ValidarAprobacionCorte` vuelve a consultar autorización, hash, vínculos,
  habilitación, membresía efectiva de ambos roles y ausencia de revocación al
  ejecutar. Su contexto OWNER se usa para leer metadatos de ambos usuarios;
  preparar/aprobar conservan la identidad del llamador.
- La autorización se revoca por un nuevo registro, no por editar el histórico:
  `EXEC E201.usp_RevocarCorteSSMS @IdSolicitud=..., @Motivo='...';`.

`IdSolicitud` es el ID **local** de `AutorizacionSSMS`, no un ID de E0-08. Al
integrar la cola se sustituye este origen con un adaptador revisado; no se
mezclan IDs ni se declara completada E0-08. Un dbo conserva su capacidad
administrativa; ejecutar todo como dbo compartido no prueba segregación humana.

## Preparación del DBA, una vez

Primero, cada contador abre su propia conexión SSMS y comunica estos resultados
al DBA por el procedimiento habitual de verificación de identidades:

```sql
SELECT ORIGINAL_LOGIN() AS LoginOriginal, USER_NAME() AS UsuarioBD,
       CONVERT(varchar(170), USER_SID(), 2) AS PrincipalSID;
```

Después de instalar 004, el DBA vincula usuarios **existentes** y verificados.
Completar los valores siguientes; el bloque falla si quedan vacíos. No crea
logins, contraseñas ni usuarios ficticios:

```sql
DECLARE @Preparador sysname=N'', @LoginPreparador nvarchar(128)=N'', @UsuarioPreparador int=NULL;
DECLARE @Aprobador sysname=N'', @LoginAprobador nvarchar(128)=N'', @UsuarioAprobador int=NULL;
DECLARE @Evidencia varchar(500)=''; -- verificación de ambos contadores/alcance institucional
IF NULLIF(@Preparador,'') IS NULL OR NULLIF(@Aprobador,'') IS NULL
 OR NULLIF(@LoginPreparador,'') IS NULL OR NULLIF(@LoginAprobador,'') IS NULL
 OR @UsuarioPreparador IS NULL OR @UsuarioAprobador IS NULL OR NULLIF(@Evidencia,'') IS NULL
 OR @Preparador=@Aprobador OR @LoginPreparador=@LoginAprobador OR @UsuarioPreparador=@UsuarioAprobador
 THROW 56410,N'Completar dos identidades distintas y verificadas.',1;
DECLARE @sidP varbinary(85),@sidA varbinary(85);
SELECT @sidP=sid FROM sys.database_principals WHERE name=@Preparador;
SELECT @sidA=sid FROM sys.database_principals WHERE name=@Aprobador;
IF @sidP IS NULL OR @sidA IS NULL OR @sidP=@sidA
 THROW 56410,N'Principales inexistentes o iguales.',1;
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 INSERT E201.IdentidadCorte VALUES
 (@sidP,@LoginPreparador,@UsuarioPreparador,1,1,@Evidencia),
 (@sidA,@LoginAprobador,@UsuarioAprobador,1,1,@Evidencia);
 EXEC(N'ALTER ROLE E201_PreparadorCorte ADD MEMBER '+QUOTENAME(@Preparador));
 EXEC(N'ALTER ROLE E201_AprobadorCorte ADD MEMBER '+QUOTENAME(@Aprobador));
 EXEC(N'ALTER ROLE E201_Ejecutor ADD MEMBER '+QUOTENAME(@Preparador));
 COMMIT;
END TRY
BEGIN CATCH IF XACT_STATE()<>0 ROLLBACK; THROW; END CATCH;
```

No conceder INSERT/UPDATE/DELETE en las tablas de autorización/recibos a los
contadores ni concederles IMPERSONATE. La ejecución puede hacerla el preparador
una vez que la otra persona autorizó; no puede crear su propia autorización.

## Fase 1: congelar el plan, conexión del preparador

Usar fecha/hora, importes, alcance y evidencia del corte real conciliado.
Formato de JSON (las etiquetas de reemplazo NO son datos a aprobar):

```json
{
  "IdPlan": "<UUID nuevo del plan>",
  "IdCorte": "<UUID de la captura conciliada>",
  "FechaCorte": "<fecha y hora del corte en Ecuador>",
  "NumeroAsiento": "<número reservado válido y sin usar>",
  "IdFechaContable": 0,
  "IdAgencia": "<agencia de registro acordada>",
  "PreparadoPor": 0,
  "Alcance": "EFECTIVO_AHORRO",
  "Controles": [
    {"CodigoAuxiliar":"11010505","IdCustodio":"BOVEDAS","Monto":0,"Fuente":"<control físico>","Evidencia":"<export real>"},
    {"CodigoAuxiliar":"11010510","IdCustodio":"JORNADAS","Monto":0,"Fuente":"<control físico>","Evidencia":"<export real>"},
    {"CodigoAuxiliar":"11010515","IdCustodio":"ATM","Monto":0,"Fuente":"<control físico>","Evidencia":"<export real>"},
    {"CodigoAuxiliar":"21013505","IdCustodio":"AHO001-PN","Monto":0,"Fuente":"<captura ahorro>","Evidencia":"<export real>"},
    {"CodigoAuxiliar":"21013510","IdCustodio":"AHO001-PJ","Monto":0,"Fuente":"<captura ahorro>","Evidencia":"<export real>"}
  ],
  "ConciliacionAhorro": {
    "Libro210135":0,"LibroPN":0,"LibroPJ":0,
    "OperativoPN":0,"OperativoPJ":0,"LineasSinMapeo":0,
    "EsEnsayo":false,"Evidencia":"<captura conciliada confirmada>"
  }
}
```

Los ceros son marcadores de formato, no saldos propuestos. Si el corte confirmó
los importes anteriores, PN es 86.646,76 y PJ 76.000,00; usar el export real como
fuente. Los custodios pueden desglosarse por ID: el motor los agrega por auxiliar.
El período debe estar abierto y FechaCorte coincidir con IdFechaContable. Este
modelo contabiliza en esa fecha; no usar una captura vieja para retrofechar un
asiento sin aprobación contable. Si el libro cambió, preparar un corte nuevo.

```sql
DECLARE @IdPlan uniqueidentifier='<UUID del JSON>';
DECLARE @Contenido nvarchar(max)=N'<JSON REAL COMPLETO>';
EXEC E201.usp_PrepararCorte @IdPlan=@IdPlan,@Contenido=@Contenido;
```

Devuelve el contenido congelado, HashPlan SHA256 hexadecimal y versión del
objetivo. SHA2_256 se calcula sobre los bytes UTF-16LE de nvarchar; no rehacer
el JSON en otra serialización después de revisarlo. Las cuentas nuevas se
identifican por código y atributos heredados, nunca por IDs todavía inexistentes.

## Fase 2: autorizar y registrar recibo, OTRA conexión del aprobador

Revisar el JSON completo y la versión, cotejar con los exports conciliados y
copiar el hash revisado (no seleccionar automáticamente el hash más reciente):

```sql
EXEC E201.usp_AprobarCorteSSMS
 @IdPlan='<UUID revisado>',
 @HashEsperado=0x<HASH_SHA256_REVISADO>,
 @Comentario='Revisé el corte, los destinos y la conciliación PN/PJ y custodios';
```

Esta es la llamada que **emite la autorización y registra el recibo validado**;
devuelve `IdSolicitud`. Internamente llama a:

```sql
EXEC E201.usp_RegistrarAprobacionReal @IdSolicitud=<ID_GENERADO>, @IdPlan='<UUID revisado>';
```

Llamar a Registrar sin una autorización auténtica anterior se rechaza. No se
rellena ReciboReal con un INSERT manual. Se impide autorizar dos veces el plan.

## Fase 3: ejecutar el corte

Desde la conexión del ejecutor habilitado, sin transacción externa:

```sql
EXEC E201.usp_EjecutarCorte @IdSolicitud=<ID_GENERADO>;
```

El resultado final es `CORTE_EJECUTADO`; un reintento da `YA_EJECUTADA`. Cualquier
error previo al commit deja las cinco altas y los cambios de imputabilidad
revertidos junto con el asiento. No ejecutar el antiguo 001 de altas por separado.

## Pruebas y límites

`resultados_corte_atomico.json` contiene el ensayo actualizado y la base local.
Se comprobó la estructura sin cambios de datos, instalación sin altas, rechazo
sin vínculo/permiso, rechazo de la misma conexión original aunque use otro
usuario por EXECUTE AS, falta de fuente auténtica, pérdida de permiso al ejecutar,
inmutabilidad y rollback inducido al contabilizar, incluyendo hijas y flags.
También se ensayó ejecución única concurrente y conservación del histórico y
de los totales por elemento.

El caso exitoso usa una fila de autorización **simulada por el DBA del laboratorio**
porque el ejecutor dispone de un único login autenticado. No se sustituyó el
validador nativo por un stub. La emisión positiva desde dos logins reales queda
como comprobación de las dos personas en SSMS, antes del corte productivo.
Esto no constituye prueba de E0-08 ni de WorkOS ni de permisos reales de Azure.

La conciliación de ahorro confirmada por el usuario levanta aquel pendiente de
conciliación, sujeto a incorporar su evidencia real al plan. Cartera 9.507,06 y
los otros destinos siguen pendientes de E9 y de la revisión de auxiliares.

Para repetir el ensayo en esta estación, defina E201_FIXTURES con la ruta
del laboratorio local que contiene las dos proyecciones JSON
ac01-completar-readonly.json y e201-inspect.json. Desde el directorio raíz
de esta rama, ejecute python Backend/tests/integration/e201_corte_atomico_lab.py.
El ensayo crea una base con nombre CooperativaDB_E201_Lab_<id>.

## Revisión del CUC Segmento 1

Se revisaron 1.182 códigos únicos del CSV de AC-01, con caracteres numéricos
ASCII, nivel regulatorio válido y todos los padres esperados presentes.
110105, 210135, 199025 y 299005 pertenecen al catálogo. Los auxiliares de
ocho dígitos pertenecen al plan interno. Para efectivo se aplican 11010505,
11010510 y 11010515 de #371. El catálogo AC-01 asignaba sufijos 01, 02 y 03
al mismo propósito y esas cuentas deben conciliarse si fueron instaladas.

005_auxiliar_faltantes.sql habilita el código 19902505 citado en #371.
Puede agregar la subcuenta 199025 bajo 1990 si el mayor está instalado;
un padre 199025 imputable requiere revisar su reclasificación antes de
aplicar el script. El código 299005 es una subcuenta CUC. Falta confirmar
el código auxiliar de sobrantes y los destinos, reglas y saldos del resto
de la sección 5.2 antes de preparar el corte completo.

El contraste puntual de 110105, 199025, 210135 y 299005 se hizo también
contra el PDF CUC codificado de octubre de 2023 (páginas PDF 22, 40 y 44)
y el plan del 24 de septiembre de 2025 (páginas PDF 1, 13 y 16).
El PDF de 2025 corresponde a la resolución SB-2025-02319 y usa otra matriz de usuarios. El ensayo conserva como base el CSV del CUC del Segmento 1 de SEPS de 2023.

## Resolución SEPS-IGT-2025-100

El CSV operativo 2025 se encuentra junto a los scripts de E2-01. Al
contrastar las 71 filas de las dos páginas del Anexo 1 con el CSV y el
seed AC-01 de 2023, la única alta aplicable a Segmento 1 fue 740640.
El CSV consolidado contiene 1.183 códigos. Los nombres existentes se
conservan cuando la diferencia en el anexo es de formato editorial.

Ejecutar 002_cuc_seps_2025_100_segmento_1.sql después de 001 y antes de 004.
Es el delta sobre el CUC base, no una recarga de la semilla histórica.
Crea 740640 como subcuenta regulatoria acreedora, no imputable, de 7406.
El Anexo 2 cambia la descripción y dinámica del grupo 33 y de 7406. El
script registra resúmenes en Descripcion y el criterio de uso se aplica
según el anexo. En 7406, el crédito reconoce la deficiencia o el monto del
diferimiento y el débito reconoce el gasto según el cronograma aprobado.
En 33 se mantienen los movimientos aplicables al fondo de reserva 3301.

3304, 330405 y 330410 son exclusivos de mutualistas. 3301 y sus subcuentas
330105, 330110 y 330115 conservan su ubicación. El delta se detiene si
encuentra una cuenta del prefijo 3304 y no elimina datos. La transitoria
segunda requiere autorización de la SEPS y sus instrucciones para
reclasificar provisiones. El delta solo instala el catálogo.

Fuente: https://www.seps.gob.ec/wp-content/uploads/Resolucio%CC%81n-No.-SEPS-IGT-2025-0100.pdf

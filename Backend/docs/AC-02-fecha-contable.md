# AC-02: fecha contable y corte exacto

Estado: cambio para revisión. Azure no se modificó; la migración compartida sigue pendiente de autorización y ejecución manual.

## Alcance y criterios del issue #66

- Usar `Contabilidad.fn_IdFechaContable`, sin reimplementar la regla en el backend.
- Conservar CON-01 (calendario de una fecha) y CON-02 (fecha contable vigente), ya integrados en develop.
- Verificar antes y desde el corte, viernes tarde, fines de semana, feriado y calendario agotado.
- Usar la hora de Ecuador continental (UTC-5) independientemente de la zona del servidor.

El backend normaliza entradas con zona horaria antes de consultar SQL. Caja utiliza el mismo resolutor. Ventanilla y reversos comparten un único instante para resolver la fecha contable y guardar la transacción; el movimiento de caja conserva la hora de su transacción. Las operaciones configuradas de consulta ATM ya utilizan la función SQL y no se reemplazan.

La función actual redondea `CAST(@FechaHora AS time(0))`: 18:59:59.500 pasa a 19:00. La migración cambia esa comparación a `time(7)`. Antes de las 19:00 permanece el día actual; desde las 19:00 se busca el siguiente día contable. Se mantienen calendario, feriados y retorno NULL cuando el calendario se agota; el backend conserva el error CALENDARIO_SIN_FECHA (HTTP 500, equivalente operativo al error DB 51016).

No se modifica el historial de clientes, la autenticación, la numeración ni la configuración de asientos contables. Tampoco se cambian las marcas de hora de cuadre/cierre, tablas o columnas. No se recalculan registros históricos.

## Scripts SQL versionados

En `Backend/scripts/sql/ac02/`:

- `001_corte_precision.up.sql`: ALTER de la función existente, con el único cambio funcional time(0) a time(7) en la comparación.
- `validar_corte.sql`: SELECT con 13 casos; compara función instalada y expresión propuesta.
- `001_corte_precision.down.sql`: restaura el comportamiento anterior, incluido su redondeo.

Estos scripts se ejecutan manualmente. Añadirlos a Git o arrancar FastAPI no los aplica. Las pruebas de lectura tampoco ejecutan up/down. El laboratorio descrito abajo sí lo hace, solo cuando se activa expresamente y únicamente en su base marcada.

Antes de desplegar en el entorno compartido, coordinar con F-08/DB, guardar y cotejar la definición vigente para no sobrescribir cambios ajenos, revisar permisos y SET ANSI_NULLS/QUOTED_IDENTIFIER. La reversión de la función no deshace operaciones registradas después de aplicar el cambio.

### Procedimiento para quien revise y ejecute la migración

1. Confirmar en el PR quién asumirá la ejecución y cuándo. Si se solicita que el autor la haga, debe recibir confirmación expresa antes de modificar Azure; publicar o aprobar el PR no implica haberla ejecutado.
2. Conectarse al entorno autorizado con la herramienta SQL del equipo y seleccionar CooperativaDB. Comprobar la conexión y guardar la definición actual de la función con estas consultas de lectura:

```sql
SELECT DB_NAME() AS BaseActual;
SELECT OBJECT_DEFINITION(OBJECT_ID(N'Contabilidad.fn_IdFechaContable')) AS DefinicionActual;
SELECT uses_ansi_nulls, uses_quoted_identifier
FROM sys.sql_modules
WHERE object_id = OBJECT_ID(N'Contabilidad.fn_IdFechaContable');
```

3. Cotejar esa definición con el script revisado. El cambio funcional previsto es exclusivamente `CAST(@FechaHora AS time(0))` a `time(7)` en la comparación. Si hay otros cambios de compañeros, conciliarlos antes de ejecutar. Mantener las opciones de sesión revisadas y disponer del permiso ALTER correspondiente.
4. Ejecutar `Backend/scripts/sql/ac02/001_corte_precision.up.sql` en CooperativaDB, como lote de función independiente. No ejecutarlo sobre master ni correr todos los archivos de la carpeta en conjunto: down es una reversión, no el paso siguiente normal.
5. Ejecutar `Backend/scripts/sql/ac02/validar_corte.sql`: deben resultar 13 filas con EstadoActual=OK y EstadoPropuesta=OK usando el calendario indicado. Repetir las pruebas de lectura descritas abajo y dejar evidencia y responsable en el PR.
6. Coordinar el despliegue del backend con el proceso del equipo. El workflow actual de Azure se activa en main o manualmente; un merge hacia develop no implica ese despliegue ni ejecuta SQL.

Si se autoriza revertir, usar `001_corte_precision.down.sql` solo después de revisar el destino y la definición vigente. Restaura el defecto previo de redondeo; no corrige ni deshace registros históricos.

## Laboratorio SQL real y reproducible

Se utiliza SQL Server LocalDB ya instalado: `(localdb)\MSSQLLocalDB`, autenticación Windows, base nueva `CooperativaDB_AC02_Lab`. No requiere Azure, WorkOS ni Docker. La confianza en el certificado local no cambia la configuración TLS de Azure.

El fixture contiene el esquema Contabilidad, seis columnas de FechaContable, diez filas de calendario ficticias y la función. Los IDs son ficticios. No contiene clientes, cuentas ni transacciones. Su calendario parcial sirve solo para los casos descritos; no valida la semilla completa F-07 ni replica CooperativaDB.

Se verifica IsLocalDB=1, edición Express, base exacta y marca de laboratorio antes de modificar la función. El destino no se toma de .env; se rechazan CooperativaDB/SeguridadDB y no se sobrescribe una base existente al crearla.

Desde Backend en PowerShell:

```powershell
SqlLocalDB start MSSQLLocalDB
$env:AC02_LOCAL_SQL_ENABLED='1'
# Solo si la base de laboratorio todavía no existe:
.venv/Scripts/python.exe -m tests.integration.ac02_sql_lab --create --backend-tests
# Para repetir sobre la base ya preparada:
.venv/Scripts/python.exe -m tests.integration.ac02_sql_lab --backend-tests
```

El ciclo restablece la función original solo en la base marcada, aplica up, aplica down y vuelve a aplicar up. Deja el laboratorio corregido. Se comprobó con SQL real:

| Etapa | Casos correctos |
|---|---:|
| Original | 10/13 |
| Corregida | 13/13 |
| Revertida | 10/13, los 13 resultados individuales coinciden con los originales |
| Corregida final | 13/13 |

Las pruebas de integración del backend contra ese laboratorio dieron 34 passed y 1 skipped. La omitida contrasta una transacción existente; el fixture no contiene operaciones financieras. Ocho pruebas adicionales protegen el destino del laboratorio.

## Pruebas de lectura contra una DB configurada

```text
python -m pytest tests/integration/test_ac02_corte_sql.py -q
python -m pytest tests/integration/test_contabilidad_db.py -q
```

Sin conexión configurada se omiten. Con conexión utilizan COOPERATIVA_DB_* y DB_* en un entorno privado, sin versionar claves; no necesitan login WorkOS. `test_ac02_corte_sql.py` comprueba 13 casos de la expresión propuesta y 13 de la función instalada. Conserva las siete cifras decimales como texto. Con la función antigua hay tres fallos reales; no se marcan xfail ni se ocultan. Con la corregida deben pasar los 26.

Las expectativas utilizan el calendario 2026 comprobado: 1-ene feriado, 2-ene hábil, 6-nov viernes hábil, 7/8-nov fin de semana y 9/10-nov hábiles. Revisarlo si cambia la semilla. La fecha 2099 queda fuera del calendario probado.

La prueba histórica de `test_contabilidad_db.py` se activa solo mediante `AC02_ID_TRANSACCION_PRUEBA`. Ese ID debe tener origen confirmado; el test no crea ni corrige datos. Las discrepancias históricas detectadas se mantienen como seguimiento externo, sin atribuirlas al backend actual ni asumir que sean semillas.

## Pendientes externos, sin ampliar AC-02

1. Revisar, autorizar y aplicar la migración SQL en el entorno compartido; después repetir sus pruebas de lectura. Azure todavía conserva la función anterior.
2. Mantener el calendario y feriados mediante F-07.
3. Validar en el futuro la integración con un depósito/retiro completo cuando el equipo configure numeración y contabilización de AC-01. El proveedor actual responde 501 OPERACION_NO_HABILITADA; no se habilita ni se inventan reglas en este cambio. AC-02 es una dependencia de AC-01, no una implementación de AC-01.
4. Aclarar el origen y tratamiento de registros históricos discrepantes con el responsable de los datos.

La regla de fecha contable y su migración/reversión están verificadas en SQL local. La aceptación desplegada en Azure sigue pendiente hasta aplicar el cambio autorizado. El flujo financiero completo es una prueba de integración posterior, no una condición para implementar sus reglas dentro de este PR.

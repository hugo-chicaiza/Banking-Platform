# Prueba funcional local de ATM-01

La capa de aplicación se puede probar completamente en local sin una base real.
Se utiliza la aplicación original `app.main.app`, su ruta registrada, middlewares,
dependencia de credencial, servicio ATM, fábrica `obtener_hsm()`, custodia AES-GCM,
PIN Block ISO-4, Offset IBM 3624 y emisor JWT RS256. La criptografía no se simula
mediante mocks. Se sustituyen las conexiones/repositorios y la escritura de
auditoría por mocks y estado en memoria.

Esto es integración funcional HTTP/ASGI con persistencia simulada. Para demostrar
también las consultas, restricciones, triggers y transacciones SQL se necesita
una instancia **aislada y desechable de SQL Server**, que puede ser local; Azure
no es un requisito para esa segunda fase. SQLite no comprobaría los bloqueos y
la sintaxis específica que usa esta implementación. Esa fase no se ejecuta aquí.

## Ejecución reproducible

Desde la raíz del repositorio en PowerShell, con las dependencias locales instaladas:

```powershell
$env:PYTHONPATH = 'Backend'
.venv/Scripts/python.exe -B -m pytest -q --tb=short -p no:cacheprovider -o asyncio_default_fixture_loop_scope=function Backend/tests/unit/test_atm_flujo_local.py
```

No necesita `.env`, variables de Azure, cuentas WorkOS ni credenciales reales.
La fixture prohíbe conexiones SQL y externas; solo permite el loopback interno
que asyncio necesita en Windows. TestClient usa transporte ASGI en memoria, sin
levantar un servidor público ni negociar TLS. El esquema HTTPS se simula en el scope.

En cada ejecución se generan una credencial de terminal de 256 bits, claves HSM
y una clave RSA efímeras. El único archivo de configuración temporal contiene el
hash y metadatos de la credencial; el secreto, la clave RSA y las claves HSM viven
en memoria. No se genera un agente ATM ni se entrega material al frontend.
Los identificadores, PAN y PIN son fixtures ficticios. No se imprimen tokens,
cuerpos de autenticación ni material criptográfico.

## Casos comprobados

| Caso | Resultado exigido |
|---|---|
| Tarjeta activa, terminal autorizado y PIN correcto | 200; cuenta enmascarada y JWT cuya firma RS256, emisor y audiencia se verifican con la clave pública |
| Duración de sesión | `expiresIn=300` y `exp-iat=300`; el mismo token verifica a los 299 segundos y falla por caducidad a los 300 |
| Tres PIN incorrectos | 401, 401, 423; contador en memoria 1, 2, 3; PIN y tarjeta bloqueados, un historial de bloqueo, sin token |
| PIN correcto tras el bloqueo | 423; no reinicia el contador ni permite emitir sesión |
| Dos fallos seguidos de PIN correcto | El contador vuelve de 2 a 0 |
| Credencial ausente, mal formada o con secreto incorrecto | 401 antes de acceder a la persistencia de tarjeta/PIN; contador intacto |
| Logs y auditoría | Tras cada caso se comprueba que no contienen PAN, PIN, PIN Blocks, credenciales, claves o JWT; se capturan también registros DEBUG |

La búsqueda simulada recibe el hash binario calculado por el código compartido de
Tarjetas. El PAN recuperado de la custodia se descifra realmente y se contrasta con
ese hash. Los repositorios reciben y devuelven datos ficticios controlados.

El bloqueo del PIN, la tarjeta, los contadores y el historial se observan en memoria.
No representan un UPDATE SQL confirmado, ni prueban exclusión mutua entre procesos.
La cuenta devuelta concuerda con el JWT; los JOIN y filtros SQL quedan para la fase SQL.

## Lo que todavía debe validarse

1. **SQL Server aislado:** esquemas CooperativaDB/SeguridadDB, permisos, consultas,
   filtros de cuentas, UPDLOCK/ROWLOCK, concurrencia, confirmación de intentos ante
   errores HTTP y recuperación cuando solo una de las dos bases confirma cambios.
2. **Azure, solo mediante una prueba posteriormente autorizada:** despliegue y rutas,
   HTTPS efectivo tras el frontal y confianza del proxy, provisión segura del hash
   de terminal y clave JWT exclusiva, permisos del registro, caducidad, rotación y
   revocación coherentes entre workers/instancias, y coherencia de claves HSM/datos.
3. **Telemetría desplegada:** asegurar que los agentes y servicios de logs tampoco
   capturan cuerpos, cabeceras sensibles, PIN Blocks o tokens. El chequeo local
   cubre los registros de Python y los eventos de auditoría producidos en esta prueba.
4. **Modo producción:** el HSM simulado actual falla si `APP_ENV=production`.
   Esta prueba configura solamente un entorno ficticio de laboratorio; no cambia
   ese control ni demuestra que el simulador esté habilitado en Azure.
5. **Cliente ATM:** se representa su petición mediante TestClient; el futuro agente,
   su almacén de credenciales y el dispositivo/PIN pad real no están implementados.

El éxito local demuestra el comportamiento de la aplicación bajo estas condiciones,
pero no basta para declarar verificado el sistema desplegado o su persistencia real.

# Revisión de clientes y cuentas contra las propuestas ASVS y PCI

Fecha: 2026-11-17. Rama: `feat/backend-mov-boveda-solicitud-autorizacion`.

## Alcance y criterio

Se contrastó el código local de `app/modules/clientes`, `app/modules/cuentas`, sus
pruebas y los controles compartidos que los protegen con los documentos entregados
`ASVS_Proposal.md` y `PCI_Banking-Platform.md`. Se revisaron las 14 operaciones CLI
y las 9 CTA. Los documentos se utilizaron como criterios de revisión; sus propuestas
de implementación no se ejecutaron como instrucciones independientes del usuario.

Resultado: **cumplimiento parcial** de ambas propuestas. Esto no es una certificación
ASVS/PCI ni una evaluación del despliegue. No se consultaron bases de negocio ni
tenants de WorkOS, Azure o Cloudflare. Clientes y cuentas se revisaron sin modificar
su implementación. Los cambios funcionales de esta tarea pertenecen a bóvedas.

Estados: **implementado** = evidencia en código para el control concreto;
**parcial** = hay controles y brechas; **pendiente** = falta en el backend revisado;
**no verificable** = requiere evidencia del entorno o de una política externa.
Las prioridades siguientes son de remediación técnica de esta revisión.

## Hallazgos para priorizar

### 1. Alta: falta alcance de agencia en cuentas y una política verificable en clientes

**Referencias:** ASVS 8.2.2, 8.3.1, 8.4.1; PCI §3.5 #1, #2 y #5.

En cuentas, `router.listar_cuentas` transmite `idAgencia` elegido por el consumidor.
Si se omite, el repositorio no restringe agencia. El detalle, saldo, movimientos,
estado, cupos e historial trabajan por id sin comprobar la agencia del usuario.
`CuentaCreate.idAgencia` tampoco se compara con la agencia de quien abre la cuenta.
El permiso de la acción no sustituye la autorización sobre la cuenta concreta.

Evidencia: [router de cuentas](../app/modules/cuentas/router.py),
[servicio](../app/modules/cuentas/service.py) y
[repositorio](../app/modules/cuentas/repository.py);
[perfil de cliente](../app/modules/clientes/service.py).

**Comprobación HTTP local con repositorio ficticio:** un CAJERO y un ASESOR de la
agencia 001 obtienen 200 al consultar una cuenta de la agencia 002. El listado
transmite al repositorio tanto `None` como `002`, según lo que mande el consumidor.
Esto demuestra la ausencia del control de aplicación; no se probó el despliegue ni
se verificó si allí existe una política adicional de seguridad de filas en SQL.

En clientes tampoco se pasa al servicio un contexto de agencia para autorizar
lecturas/escrituras. CLI-08 agrega las cuentas y productos del cliente sin alcance
del operador. Debe definirse si la ficha de cliente es un catálogo global y cómo se
autoriza consultar sus productos de otras agencias; no debe inventarse una agencia
propietaria a partir de `CreadoPor` o de una cuenta arbitraria.

**Acción:** fijar la matriz rol × agencia × recurso, propagar contexto autenticado,
restringir SQL y agregar pruebas negativas por id, listado y escrituras. ADMIN puede
tener alcance global explícito, sin convertirlo en excepción para los demás roles.

### 2. Alta: respuestas exitosas sensibles sin protección de caché en el backend

**Referencias:** ASVS 14.3.2 y 3.4.4; PCI §3.9 #1.

Los routers de clientes/cuentas y sus respuestas exitosas no establecen
`Cache-Control: no-store` ni `X-Content-Type-Options: nosniff`. El manejador de errores
sí los establece, por lo que comprobar solo un 400/403 puede ocultar la diferencia.
No hay middleware global que complete estas cabeceras en los éxitos revisados.

Evidencia: [router de clientes](../app/modules/clientes/router.py),
[router de cuentas](../app/modules/cuentas/router.py),
[app principal](../app/main.py) y [errores](../app/core/api/errors.py).

**Comprobación:** GET exitosos de detalle de cuenta y cliente con TestClient carecen
de `Cache-Control`; el de cuenta carece también de `nosniff`.

**Acción:** aplicar cabeceras en éxitos y errores, incluyendo el DELETE 204 que
construye su propia Response. Verificar por separado las reglas de Cloudflare y
la limpieza del estado del frontend al salir de sesión.

### 3. Alta: identificación y búsquedas personales viajan en la URL

**Referencias:** ASVS 14.2.1; PCI §3.6 #7 y §3.9 #1 como controles complementarios.

CLI-01 exige `identificacion` en query string y CLI-03 admite `identificacion` y
`q` en GET. CTA-02 admite `numeroCuenta` en GET. El documento ASVS prohíbe de forma
expresa buscar cédulas por query string. Enmascarar los logs de la app no impide que
la URL quede en historial, proxies o telemetría externa.

**Acción:** añadir búsquedas POST con cuerpo validado y adaptar consumidores;
mantener los identificadores internos para detalle. Revisar también la política
de registro del número de cuenta y del texto libre. El logger de peticiones actual
ya omite la query string, lo que reduce exposición en ese logger concreto.

### 4. Media: contratos de entrada parcialmente estrictos

**Referencias:** ASVS 1.1.1, 2.2.1, 15.3.3, 15.3.5 y 15.3.7; PCI §3.7 #1.

`CuentaCreate` y `RiesgoCreate` heredan una base que permite coerciones y, por defecto,
ignora campos extra. Los otros contratos de edición suelen prohibir extras, pero
no todos sus números y booleanos son estrictos. Varios ids carecen de límites
positivos/int32 y las búsquedas antiguas no tienen tope de longitud. No se observa
una normalización uniforme previa a validar los distintos campos.

**Comprobaciones Pydantic:** `CuentaCreate` acepta `idCliente: true` como 1,
`idSubProducto: "20"` como 20 y `montoInicial: "50.001"` sin limitarlo a centavos.
`saldo` extra se ignora. `RiesgoCreate` convierte `esPEP: "true"` y omite `evaluador`
extra. **No se demostró que esos extras puedan modificar saldo o suplantar al autor**:
son campos ignorados, no una asignación masiva confirmada.

Varios endpoints antiguos tampoco usan `solo_parametros`; por ejemplo,
`GET /cuentas?pageSize=1&pageSize=2` responde 200 en lugar de rechazar duplicados.
Las rutas nuevas de estado/cupos y CTA-06 sí aplican ese helper.

Evidencia: [esquemas de clientes](../app/modules/clientes/schemas.py),
[esquemas de cuentas](../app/modules/cuentas/schemas.py) y
[modelo base](../app/core/api/schemas.py).

**Acción:** entradas por acción con extras prohibidos, ids y booleanos estrictos,
validación decimal/rango adecuada a SQL, límites de texto y parámetros inequívocos.
Los decimales expresados como texto pueden admitirse deliberadamente; exigir
`strict=True` indiscriminadamente rompería contratos válidos de fechas y dinero.

### 5. Media: no hay minimización de campos de cliente por rol

**Referencias:** ASVS 8.2.3 y 15.3.1; PCI §3.5 #1 y §3.9 #1.

CLI-03/04 usan el mismo modelo Cliente para CAJERO, ASESOR, SUPERVISOR y ADMIN.
Incluye identificación, nacimiento, teléfonos, email, consentimiento y direcciones.
Se comprobó que CAJERO y ASESOR reciben el mismo conjunto de campos en CLI-04.
Hay un `response_model` explícito, pero no la diferenciación por rol que pide la
propuesta ASVS. CTA-02 sí tiene una proyección resumida diferente del detalle.

**Acción:** definir qué campos necesita cada acción/rol y aplicar proyecciones
adecuadas; no basta con ocultarlos en el frontend. La necesidad concreta de cada
campo debe confirmarse con negocio y la política de protección de datos.

### 6. Alta: auditoría parcial y sin entrega garantizada entre bases

**Referencias:** ASVS 2.3.3, 16.2.1–16.2.5, 16.3.2–16.3.4, 16.4.2 y 16.5.3;
PCI §3.6 #1–#4 y §3.7 #5.

ClientesHis conserva cambios exitosos junto con la modificación del cliente y
direcciones en CooperativaDB. Riesgo también tiene historial transaccional.
CTA-08 conserva su modificación y CuposModHis en la misma transacción. Esas son
garantías útiles, pero no cubren todos los intentos fallidos ni equivalen a una
bitácora de seguridad completa. No se observa un evento de seguridad completo de
apertura CTA-01 ni de todos los éxitos/fallos de CTA-08 en estos servicios.

CTA-05 confirma CooperativaDB y después llama a `audit.registrar` en SeguridadDB.
Este helper captura el error de persistencia y solo lo registra en el logger; no
hay outbox ni reintento durable para garantizar la entrega. Puede existir el cambio
de estado sin su evento en la bitácora central. No basta con añadir rollback después
de un commit: hace falta diseñar entrega durable/recuperación entre bases.

La bitácora central escribe hora local de Ecuador sin zona, en lugar del UTC que
piden los documentos; carece de agencia como metadato y no todas sus descripciones
incluyen antes/después y correlación. No se observa encadenamiento HMAC de eventos.
ClientesHis sí utiliza UTC en los registros nuevos. La protección real de permisos
SQL sobre la bitácora y sus historiales no se verificó en el entorno.

Evidencia: [servicio de cuentas](../app/modules/cuentas/service.py),
[persistencia de auditoría](../app/core/security/audit.py),
[historial del cliente](../app/modules/clientes/repository.py).

El historial actual de cupos no conserva cambios de frecuencia ni fecha de vigencia;
es una limitación ya documentada en `trazabilidad-clientes-cupos.md`, cuya ampliación
fue revertida por decisión previa. Requiere acordar el alcance antes de ampliarlo.

**Acción:** diseñar eventos y política de retención, registrar fallos relevantes,
unificar UTC/agencia/correlación y garantizar entrega durable e integridad, con
pruebas de fallo. Respetar la clasificación de PII en el historial de clientes.

### 7. Media: límites de consumo de recursos incompletos

**Referencias:** ASVS 2.4.1 y 15.2.2; PCI §3.7 #6.

Los listados principales e historiales CLI-07/CTA-09 tienen páginas de hasta 100;
el rate limit compartido existe. Sin embargo, cuenta por IP y proceso, no también
por usuario ni de forma distribuida. No se encontró un límite global de tamaño de
body ni un timeout de consultas SQL: `Connection Timeout` limita la conexión, no
la ejecución. CTA-06 valida el orden de fechas pero no un rango máximo de consulta.
CLI-14 devuelve todo el historial de riesgo sin paginación; CLI-08 agrega todos los
productos, y CLI-09 todas las direcciones.

**Acción:** topes y políticas para listas anidadas, historial y búsquedas; timeout
de ejecución y tamaño de petición; cuotas por usuario/IP coordinadas con la capa
de infraestructura. Verificar las limitaciones del Worker/App Service por separado.

Evidencia: [rate limit](../app/core/api/rate_limit.py),
[motor SQL](../app/core/database/db.py),
[configuración](../app/core/config/settings.py).

## Controles con evidencia favorable y sus límites

| Control | Clientes | Cuentas | Evidencia / límite |
|---|---|---|---|
| Sesión exigida y rol/permiso por acción | Implementado | Implementado | Dependencias de routers y matriz automática de autorización; no sustituye alcance por agencia |
| AUDITOR sin escritura en estos dos módulos | Implementado por asignación inicial | Implementado por asignación inicial | Sus roles de consulta están separados; los permisos reales del tenant pueden cambiar |
| Identidad de quien escribe desde la sesión | Implementado | Implementado | UsuarioAuditoria; extras ignorados en algunos modelos siguen siendo una brecha de validación |
| SQL parametrizado / orden con lista permitida | Implementado en repositorios revisados | Implementado en repositorios revisados | Parámetros ligados y CASE/whitelists; no se revisó el cuerpo de SP instalados en el servidor |
| Serialización JSON, sin deserialización de objetos ejecutables | Implementado en el alcance | Implementado en el alcance | Pydantic/FastAPI; no se observó eval, exec ni pickle en estos módulos |
| Reglas de negocio y transacciones | Parcial | Parcial | Consentimiento, documento, tipo de persona, catálogos, transiciones, cierre con saldo/deuda, límites de cupos y rollback; falta agencia y auditoría completa |
| Bloqueos en modificaciones compartidas | Implementado en operaciones revisadas | Implementado en operaciones revisadas | Cliente, direcciones, estado y cupos usan bloqueos; garantía de apertura completa depende también del SP instalado |
| PAN/PIN fuera de respuestas | Implementado en proyecciones revisadas | Implementado en proyecciones revisadas | Perfil usa tarjeta enmascarada y modelos explícitos; no implica evaluación del HSM/tarjetas |
| Errores genéricos, id de correlación, sin SQL | Implementado para errores inesperados/SQL | Implementado para errores inesperados/SQL | ProblemDetailsRoute; algunos mensajes de negocio de clientes repiten datos recibidos y deben revisarse por clasificación |
| Protección CSRF compartida | Parcial respecto al texto de PCI | Parcial respecto al texto de PCI | Verificar_origen valida Origin/Sec-Fetch-Site, pero no exige token/cabecera CSRF ni JSON en todas las escrituras; faltan pruebas de la política completa de navegador/Worker |
| Cabeceras de caché en éxitos / parámetros personales en URL | Pendiente | Pendiente/parcial según ruta | Hallazgos 2 y 3 |
| Autorización por campo / tipos estrictos uniformes | Parcial | Parcial | Hallazgos 4 y 5 |
| Registro de todos los fallos e integridad de auditoría | Parcial | Parcial | Hallazgo 6 |

La autorización de routers es un control del servidor válido; el requisito ASVS
8.3.1 se satisface solo parcialmente si se interpreta literalmente como políticas
reutilizables en los servicios: no todos reciben el contexto autenticado. Las reglas
de negocio existentes no deben eliminarse al introducir esa autorización.

## Evidencia pendiente fuera de los módulos

- WorkOS: MFA, bloqueo, timeout de inactividad de 15 minutos, duración absoluta,
  revocación y permisos efectivos. El uso del SDK no demuestra estas configuraciones.
- Cloudflare/Azure: reglas no-cache, TLS por salto, restricciones de origen, CSP,
  Referrer-Policy, CORS, límites de peticiones y cuerpo. El backend soporta secreto
  de proxy e IP confiable, pero `proxy_exigido` es configurable y no prueba el entorno.
- SQL: identidades y privilegios mínimos, auditoría inmutable, retención, cifrado y
  ausencia de cuentas predeterminadas. La configuración admite TLS y Managed Identity,
  pero hay que comprobar sus valores efectivos sin publicar secretos.
- CI/CD y documentación: evidencia de controles bloqueantes, SBOM, hashes/lockfiles,
  protección de ramas, despliegue y recuperación, inventario de datos y retención.
- Archivos de cliente: estos routers no reciben UploadFile. El control de carga de
  archivos de PCI §3.7 #8 queda condicional para otra funcionalidad.
- Criptografía de PAN/PIN, HSM y ATM se delega a sus módulos; no es una exigencia de
  implementar cifrado de tarjetas dentro de clientes o cuentas.

## Comprobaciones realizadas

- Lectura de ambos documentos, routers, esquemas, servicios, repositorios y pruebas.
- Comprobaciones HTTP en proceso, con sesión y repositorios ficticios: alcance de
  agencia, cabeceras, campos por rol y parámetros repetidos. Sin datos reales.
- Comprobaciones directas de modelos Pydantic con valores ficticios (hallazgo 4).
- Suite automática existente de clientes/cuentas y controles compartidos. Su éxito
  demuestra regresión funcional; no demuestra cumplimiento completo de las propuestas.
- Resultado de la suite completa tras ampliar ADMIN en bóvedas: **3.457 pruebas
  aprobadas y 271 omitidas**, con 4 advertencias existentes. Las omitidas no se
  presentan como evidencia de cumplimiento. Ruff y Pyright sin errores.

## Orden sugerido

1. Acordar e implementar alcance de agencia y campos por rol; añadir pruebas IDOR.
2. Aplicar no-store/nosniff y trasladar búsquedas personales a cuerpos POST.
3. Homogeneizar contratos estrictos y rechazo de parámetros repetidos.
4. Completar auditoría durable, metadatos e integridad, y acordar retención.
5. Completar límites/timeout y reunir evidencia de WorkOS, infraestructura y CI.

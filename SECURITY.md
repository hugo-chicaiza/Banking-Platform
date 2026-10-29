# Política de seguridad

Este repositorio es **público** y la aplicación maneja datos de clientes de una
cooperativa: documentos de identidad, saldos, movimientos y datos de tarjeta.
Las dos cosas juntas hacen que la higiene de seguridad no sea opcional.

Documento de F-02 ([#16](https://github.com/hugo-chicaiza/Banking-Platform/issues/16)).

## Reportar un problema

**No abras un issue público.** Un issue describe el problema a cualquiera que
lea el repositorio antes de que esté corregido.

En su lugar:

1. Usa **Security → Report a vulnerability** (GitHub Private Vulnerability
   Reporting), o
2. escribe en privado a quien mantiene el repositorio
   ([@hugo-chicaiza](https://github.com/hugo-chicaiza)).

Incluye: qué se puede hacer, cómo reproducirlo, y qué datos u operaciones
quedan expuestos. Si encontraste una credencial filtrada, **no la pruebes**:
dilo y punto.

## Si se filtró una credencial

Pasa, y lo importante es la reacción. Borrar el archivo **no es suficiente**:
el valor sigue en el historial de Git, en los forks, en los clones de cada
quien y en la caché de GitHub.

**Orden correcto:**

1. **Rotar la credencial.** Primero. Antes de limpiar el historial, antes de
   abrir el PR, antes de avisar a nadie. Hasta que se rote, sigue siendo
   válida.
2. **Avisar** a quien mantiene el repositorio, en privado.
3. **Revisar los accesos** de esa credencial: qué pudo hacer alguien con ella
   mientras estuvo expuesta.
4. **Quitarla del historial** solo después de los pasos anteriores, y
   coordinado con el equipo: reescribir el historial obliga a todos a volver a
   clonar.

Lo que **no** sirve: un commit que borre el archivo, un `--amend`, o un
`.gitignore` añadido después.

## Lo que el repositorio ya hace por ti

Controles automáticos que corren en cada PR. Están aquí para que sepas qué te
cubre y qué no.

| Control | Dónde | Qué detecta |
| --- | --- | --- |
| **gitleaks** | `backend-ci.yml` (acción fijada por SHA) | Credenciales en el diff y en el historial. `.gitleaks.toml` añade reglas propias: cadenas de conexión a SQL Server, claves de firma, perfiles de publicación de Azure y números de tarjeta. |
| **Archivos prohibidos** | `pr-governance.yml` | Bloquea el PR que añada `.env`, `.pem`, `.key`, `.pfx` o un perfil de publicación. |
| **bandit** | `backend-ci.yml` | Patrones inseguros en Python. |
| **CodeQL** | `codeql.yml` | Flujo de datos entre archivos: un valor de la petición que llega sin validar a una consulta, a un `eval` o a una respuesta. |
| **pip-audit / npm audit** | `backend-ci.yml`, `frontend-ci.yml` | Vulnerabilidades conocidas en las dependencias. |
| **Instalación verificada** | `backend-ci.yml` | `pip --require-hashes --only-binary :all:`: versiones verificadas por hash y sin ejecutar `setup.py`. |
| **Dependency review** | `dependency-review.yml` | La dependencia que **el PR añade**, con su vulnerabilidad y su licencia, antes de integrarla. |
| **Dependabot** | `.github/dependabot.yml` | Abre el PR de actualización en cuanto se publica un aviso de seguridad. |
| **SonarQube** | `backend-ci.yml`, `frontend-ci.yml` | *Security hotspots* y deuda técnica del código nuevo. Requiere `SONAR_TOKEN`. |
| **ESLint** | `frontend-ci.yml` | Bloquea `localStorage`, `sessionStorage`, `console.*`, `eval` y `bypassSecurityTrust*`. |
| **CSP verificada** | `frontend-ci.yml` | Falla si el artefacto de producción sale sin Content-Security-Policy estricta. |

*(parte 2)* Se añadirán `trivy` sobre la imagen del backend, la comprobación de
que el contenedor no corre como root y la generación del SBOM.

Ninguno sustituye el criterio al escribir el código. Un control automático
detecta el patrón conocido; no detecta una regla de autorización mal pensada.

## Controles en la propia aplicación

La columna OWASP remite a [OWASP Top 10:2025](https://owasp.org/Top10/2025/).

### Frontend — activos

| Control | Dónde | Riesgo que cubre | OWASP |
| --- | --- | --- | --- |
| CSP estricta por hash | `Frontend/angular.json` (`security.autoCsp`) | XSS: el navegador solo ejecuta los scripts cuyo hash está en la política | A03 |
| Subresource Integrity | `Frontend/angular.json` | Un script alterado en tránsito o en el CDN se rechaza | A03 |
| `no-console` como error | `Frontend/eslint.config.mjs` | La consola del navegador la lee el usuario y cualquier extensión; aquí circulan saldos y datos de tarjeta | A09 |
| `localStorage`/`sessionStorage` bloqueados | `Frontend/eslint.config.mjs` | Un token guardado ahí queda expuesto a cualquier XSS. Dónde vive el token lo decide F-03 | A07 |
| `bypassSecurityTrust*` bloqueado | `Frontend/eslint.config.mjs` | Desactiva el saneado de Angular, que es su defensa contra XSS | A03 |
| Promesas sin manejar prohibidas | `Frontend/eslint.config.mjs` | Una llamada HTTP sin manejar pierde en silencio el resultado de una operación de dinero | A10 |
| Sin secretos en el bundle | `Frontend/src/environments/**` | Todo lo que se compila viaja al navegador y cualquiera lo lee | A02 |
| `apiBaseUrl` relativo en los tres entornos | `Frontend/src/environments/**` | El host del backend no queda escrito en un bundle público, y no hace falta abrir CORS | A01 |
| TLS a la base obligatorio en Azure | `Backend/.env.example` (`DB_ENCRYPT=yes`) | Interceptación de la conexión a la base | A04 |
| Autenticación sin credenciales | `Backend/app/core/config.py` (`DB_AUTH_MODE=managed_identity`) | Entra ID en lugar de usuario y contraseña: no hay credencial que robar | A07 |

> Los dos últimos ya estaban en `develop` antes de esta entrega. El modo
> `managed_identity` es la mejor decisión de seguridad que tiene hoy el
> proyecto y conviene que sea el modo por defecto en Azure.

### Backend — llegan en la parte 2 de F-02

Están implementados y probados, pero se entregan en un PR aparte porque se
construyen sobre el `Backend/` que ya existe en `develop`:

| Control | Riesgo que cubre | OWASP |
| --- | --- | --- |
| Validación estricta de la configuración al arrancar en staging y producción | El `.env` de desarrollo copiado a un servidor real | A02 |
| Una variable de entorno desconocida impide el arranque | `APP_ENV` mal escrito: arranca con otra configuración y sin avisar | A02 |
| Enmascarado de contraseñas, PIN, PAN, tokens y cédulas en los logs | Datos sensibles en el agregador, de donde no se pueden retirar | A09 |
| `X-Request-Id` saneado y propagado | Falsificación de entradas en el log (CWE-117), reflejo en cabecera (CWE-113) | A09 |
| Cabeceras de seguridad, **también en las respuestas de error** | Respuesta interpretada como HTML, embebido en iframe, caché de saldos | A03 |
| Error interno genérico, sin traza ni SQL | Revelar estructura interna, consultas y versiones a quien provoca el error | A10 |
| El error de validación no devuelve el valor enviado | Devolver la contraseña o el PIN que acaba de fallar la validación | A09 |
| `/docs` cerrado en producción | Inventario completo de endpoints público | A02 |
| CORS con lista explícita, solo `https` en entornos desplegados | Cualquier sitio llamando a la API con las credenciales del usuario | A01 |
| El motor nunca registra las consultas con sus parámetros | Saldos, documentos y hashes en la salida estándar | A09 |
| Sin `autocommit`; `rollback` al fallar | Una operación de dinero confirmada a medias | A06 |
| Imagen con usuario sin privilegios, verificado en el CI | Un proceso comprometido con permisos de root | A02 |

## Reglas al escribir código

Cinco reglas. Las cinco corresponden a un incidente real y habitual en
aplicaciones financieras.

1. **Toda consulta va con parámetros enlazados.** Nunca
   `f"SELECT ... WHERE id = {valor}"`, ni en un `repository.py`, ni en un
   script, ni en una prueba. (A05 — *Injection*)

2. **Las contraseñas y los PIN solo existen como hash.** Nunca en texto plano:
   ni en la base (`ClaveHash`), ni en un log, ni en una variable que acabe en
   un mensaje de error, ni en los datos de prueba. (A07 — *Authentication
   Failures*)

3. **Nada sensible en una URL.** Ni en la ruta, ni en la query string. Las URL
   quedan en el historial del navegador, en los logs del proxy y en la cabecera
   `Referer`. Un identificador de cliente en la ruta es inevitable; una cédula
   o un token, no. (A09)

4. **Un dato nuevo que sea sensible se añade a `SENSITIVE_KEYS`**
   (`Backend/app/core/logging.py`, parte 2) en el mismo PR que lo introduce. El enmascarado no
   adivina nombres de campo.

5. **La autorización se comprueba en el servidor, siempre.** Que el frontend
   oculte un botón no es un control: cualquiera puede llamar al endpoint
   directamente. El rol se verifica en el `router.py`, y el acceso al recurso
   concreto (esta agencia, esta cuenta) en el `service.py`. (A01 — *Broken
   Access Control*, la categoría número uno)

## Datos de prueba

Los datos de prueba de esta aplicación **no** pueden salir de un entorno con
datos de clientes. Un respaldo de producción «anonimizado» a mano casi nunca lo
está de verdad.

- Cédulas y RUC: generados con el algoritmo de validación, no reales.
- Números de tarjeta: solo los PAN de prueba que publican las marcas
  (`4111111111111111` y equivalentes). Están en la lista de excepciones de
  `gitleaks` precisamente porque no corresponden a ninguna cuenta.
- Nombres, direcciones y teléfonos: inventados.

La generación reproducible de la semilla es alcance de F-07
([#107](https://github.com/hugo-chicaiza/Banking-Platform/issues/107)).

## Alcance

Esto es un proyecto académico en desarrollo. **No** está certificado para
operar con dinero real ni con datos de clientes reales, y no ha pasado una
auditoría de seguridad. Lo documentado aquí son las prácticas que el equipo
aplica, no una declaración de cumplimiento.

## Referencias

- [OWASP Top 10:2025](https://owasp.org/Top10/2025/)
- [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
- [OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/)
- [OWASP Secure Headers Project](https://owasp.org/www-project-secure-headers/)
- [GitHub — Private vulnerability reporting](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)

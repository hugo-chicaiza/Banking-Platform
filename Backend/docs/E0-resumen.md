# E0 · Qué se implementó y para qué sirve

Resumen corto de cada E0 de esta fase: su objetivo, qué quedó hecho y dónde está.
Lo que falta activar está en [E0-pendientes.md](E0-pendientes.md); lo de Azure, en [E0-azure.md](E0-azure.md).

| E0 | En una frase |
|---|---|
| E0-01 | Los cambios a la base se hacen con archivos versionados, no a mano |
| E0-02 | La base tiene un respaldo diario cifrado fuera de Azure y se puede restaurar |
| E0-03 | Backend y frontend comparten un contrato de la API escrito y comprobable |
| E0-05 | Toda acción importante queda en una bitácora única, inmodificable y completa |
| E0-06 | Las tareas automáticas corren una sola vez, quedan registradas y avisan si se detienen |
| E0-11 | Nada llega a `develop` ni a `main` sin pasar las revisiones de calidad y seguridad |
| E0-13 | Los registros técnicos sirven para soporte sin exponer datos sensibles |
| E0-16 | La seguridad del proyecto está documentada: activos, claves, amenazas y responsables |
| E0-18 | Todos los PDF salen con el mismo formato institucional y trazable |

---

## E0-01 · Migraciones versionadas
**Objetivo:** que la estructura de las dos bases (CooperativaDB y SeguridadDB) se pueda reconstruir desde el
repositorio y que cada cambio quede registrado: quién, cuándo y qué archivo. Se acaban los cambios a mano en la base
compartida.

**Implementado:**
- Ejecutor `python -m app.core.migraciones` (`estado`, `aplicar`): aplica en orden los `.sql` de
  `migrations/<base>/`, cada uno en su transacción, con suma SHA-256 y registro en `Migracion.Bitacora`.
- Rechaza archivos mal nombrados, repetidos o modificados después de aplicados.
- Generador de la «migración cero» (`scripts/generar_linea_base.py`) desde la estructura actual.
- Apagado por defecto (`MIGRACIONES_HABILITADAS=false`).

## E0-02 · Respaldo y restauración
**Objetivo:** no perder datos. Hay una copia diaria de las dos bases fuera de Azure, cifrada, y una forma probada de
volver a ella.

**Implementado:**
- `respaldo-bd.yml`: cada día exporta las dos bases (SqlPackage), las cifra con AES-256 y las sube a Backblaze B2
  (bucket privado; se borran a los 14 días).
- `restaurar-bd.yml`: descifra y restaura un respaldo en una base temporal, a mano.
- `ensayo-migraciones.yml`: prueba cada migración en una copia restaurada antes de la base real (apagado).
- Login SQL `AdminRespaldos`: solo lectura en las dos bases y permiso para crear la base temporal de restauración.

## E0-03 · Contrato de la API
**Objetivo:** que backend y frontend acuerden cada endpoint antes de programarlo, y que cualquier cambio del
contrato se note en la revisión.

**Implementado:**
- `scripts/contrato.py`: exporta el contrato por módulo (`Backend/contract/*.json`, 18 módulos), lo compara con el
  código y revisa las convenciones (errores, idempotencia, montos).
- Frontend: tipos generados desde el contrato (`contrato:tipos`) y un servidor simulado (`dev:contrato`) para
  trabajar sin el backend.

## E0-05 · Bitácora de auditoría
**Objetivo:** responder siempre «quién hizo qué, cuándo, desde dónde y con qué resultado». Ninguna operación de
dinero queda sin su evento, y nadie puede alterar la bitácora.

**Implementado:**
- **Formato único** de la bitácora: hora UTC, agencia, sesión, canal, código de soporte (correlación), objeto
  afectado y cambios.
- **Catálogo** `Auditoria.TipoEvento`: 68 eventos con módulo y severidad.
- **Bitácora inmodificable**: un disparador impide editar o borrar filas.
- **Saneo**: los saltos de línea se escapan (nadie puede falsificar un registro) y se ocultan tarjetas, tokens,
  PIN y secretos.
- **Operaciones de dinero dentro de su transacción**: caja, bóveda y transacciones escriben su evento en la bandeja
  junto con el movimiento, o ninguno de los dos. El relevo lo pasa a la bitácora cada minuto.
- **Montos en el evento**: leídos del mismo registro (monto y saldos de antes y después).
- **A qué apunta cada evento**: operaciones con clientes → `Transacciones.Transaccion`; internas →
  `Boveda.MovimientoBoveda`.
- **CAJ-09**: la naturaleza contable y el evento salen del catálogo de tipos de transacción, no del código.
- **ATM listo para activar** (`confirmar_atm`) y **alerta** si un evento tarda más de 10 minutos.

## E0-06 · Tareas programadas
**Objetivo:** que las tareas automáticas (recuperaciones, relevo, resúmenes) sean confiables: una sola a la vez,
registradas y con aviso si dejan de correr.

**Implementado:**
- Comando único `python -m app.core.tareas ejecutar <CODIGO>`: bloqueo por tarea, registro de cada ejecución
  (resultado, procesados, errores) y ejecución manual con motivo obligatorio.
- El web job de ATM-06 pasa por el ejecutor.
- **Vigilante** cada 5 minutos: avisa si una tarea no corrió dentro de su ventana.

## E0-11 · Pipeline y protección de ramas
**Objetivo:** que todo cambio pase revisiones automáticas antes de mezclarse, y que a `main` solo llegue lo que viene
de `develop` con aprobación.

**Implementado:**
- **Pipeline del backend en cada PR:** formato y estilo (ruff), tipos (pyright), pruebas con un piso de cobertura
  que solo puede subir, análisis de seguridad del código (bandit), dependencias vulnerables (pip-audit), secretos
  (gitleaks), SonarCloud y la lista de componentes (SBOM).
- **Reglas de rama:** `develop` exige el pipeline en verde; `main` exige origen `develop` y una aprobación.
- **Frontend:** SBOM en el pipeline.

## E0-13 · Registros técnicos
**Objetivo:** que soporte pueda diagnosticar un problema con el código de soporte (`traceId`) sin que los registros
expongan datos de clientes ni secretos.

**Implementado:**
- **Enmascarado automático:** número de tarjeta, tokens, claves y contraseñas.
- **Sin query string:** las URL se registran sin parámetros.
- **Formato:** texto o JSON.
- **Registro por petición:** usuario, agencia y roles.
- **Inventario de qué se registra, dónde y por cuánto tiempo:** `docs/inventario-registros.md`.

## E0-16 · Seguridad documentada
**Objetivo:** tener la evidencia que piden PCI, ASVS y la LOPDP: qué protegemos, dónde están las claves, qué
amenazas hay y quién responde por cada tema.

**Implementado** (`docs/seguridad/`):
- Activos sensibles, inventario de claves y herramientas.
- Política de seguridad.
- Modelo de amenazas (plantilla y uno ya hecho).
- Gobierno: roles, revisión por fase y registro de capacitación.
- Responsables de las capacitaciones: ASVS y PCI, Matthew; LOPDP e IA, Eli.

## E0-18 · Documentos PDF
**Objetivo:** que comprobantes, reportes y estados de cuenta salgan con el mismo encabezado institucional y digan
quién los generó y cuándo.

**Implementado:**
- **Generador común `DocumentoPdf`:** datos de la institución tomados del perfil de la entidad (nombre, RUC, sitio).
- **Trazabilidad:** usuario que lo generó, fecha con la zona horaria de Ecuador y pie de página uniforme.

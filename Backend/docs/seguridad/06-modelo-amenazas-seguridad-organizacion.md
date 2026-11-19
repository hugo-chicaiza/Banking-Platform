# 06 · Modelo de amenazas · Seguridad y Organización

- **Versión:** 1 (E0-16) · **Historias:** F-03, AUT-01..09, C-05, SEG-01..10, E1-01, E1-02, E1-06, E0-08
- **Alcance:** inicio y cierre de sesión (WorkOS AuthKit, patrón BFF), usuarios internos, roles `org-*`, permisos
  generales (`prd-`, `con-`), pestañas por rol, perfil de la institución, agencias, aprobaciones de dos personas.

## Activos
Sesión del usuario (C4), identidad y rol en WorkOS (C4), datos del personal (C3), configuración de la institución y
agencias (C2), bitácora de auditoría (C3). Ver [activos](01-activos-sensibles.md).

## Flujo y límites de confianza
Navegador → **Worker de Cloudflare** (cabeceras, `X-Proxy-Secreto`) → **backend** (`require_auth`, `require_roles`,
`require_permiso`) → SeguridadDB / CooperativaDB; backend ↔ **WorkOS** (API con `WORKOS_API_KEY`). El navegador nunca
recibe tokens: solo la cookie `__Host-` cifrada.

## Amenazas

| Id | STRIDE | Amenaza | Control existente | Pendiente |
|---|---|---|---|---|
| S-1 | Suplantación | Robo o reutilización de la cookie de sesión | `HttpOnly`, `Secure`, `__Host-`, `SameSite`; sesión única y revocación al cambiar rol o bloquear (AUT-08/09) | Límites de sesión E1-07 |
| S-2 | Suplantación | Llamar al backend saltando el proxy y fijar la IP | `PROXY_EXIGIDO` + `X-Proxy-Secreto`; IP solo de la cabecera del proxy | — |
| T-1 | Manipulación | Cambiar un rol o permiso desde un rol no autorizado | Endpoints SEG/AUT solo `org-admin`; matriz `test_autorizacion.py` cubre cada ruta | — |
| T-2 | Manipulación | Usar el rol de entorno `admin` de WorkOS para entrar | `normalizar_roles` solo acepta `org-*` (#445) | — |
| R-1 | Repudio | Negar un cambio administrativo | Auditoría de cada cambio y denegación con roles y `traceId` | Correlación y UTC en la bitácora (E0-05) |
| I-1 | Divulgación | Datos personales en registros o en la URL | Sin query string en registros; `enmascarar` (E0-13) | — |
| I-2 | Divulgación | Mostrar datos internos (slugs `org-*`) en la UI | La UI muestra solo el nombre del rol | — |
| D-1 | Denegación | Fuerza bruta contra el inicio de sesión o la API | WorkOS protege el inicio de sesión; límite de peticiones del backend | — |
| E-1 | Elevación | Un usuario de una agencia opera sobre otra | Alcance por agencia en consultas y escrituras; multiagencia (#450) | — |
| E-2 | Elevación | Un ADMIN se quita a sí mismo o al último administrador | Regla del último ADMIN; pestañas de Seguridad no configurables | — |
| E-3 | Elevación | Una persona aprueba su propia solicitud | Aprobación de dos personas con identidades distintas (E0-08) | — |
| E-4 | Elevación | Mostrar una pestaña a un rol hace creer que tiene acceso | La configuración de pestañas solo cambia el menú; cada API valida rol o permiso | — |

## Casos de abuso
Un administrador malicioso se asigna un permiso de contabilidad para aprobar sus propios asientos → mitigado por la
aprobación de dos personas y la auditoría de `ASIGNAR_PERMISO_ROL`; revisar en la evaluación periódica de roles.

## Riesgos aceptados
- Base compartida que también es producción (P4-11): ver [gobierno](07-gobierno.md).

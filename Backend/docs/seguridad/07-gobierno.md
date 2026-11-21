# 07 · Gobierno de la seguridad

## Roles y responsabilidades

| Rol | Quién | Responsabilidades |
|---|---|---|
| Responsable de seguridad y de la evidencia | `hugo-chicaiza` (P4-5) | Mantener estos documentos, aprobar excepciones, ejecutar migraciones y respaldos en la base compartida, coordinar incidentes |
| Equipo de desarrollo (backend, frontend, base de datos) | Integrantes del proyecto | Aplicar la política, actualizar inventarios y modelos de amenazas en cada historia, revisar los pull requests |
| QA | Integrantes asignados | Verificar criterios de aceptación de seguridad y pruebas negativas |
| Institución (cliente) | Cooperativa | Notificación a titulares y autoridades (LOPDP, SEPS); administración de usuarios con rol administrador |

## Registro de capacitación

| Tema | Responsable | Estado | Fecha | Duración | Evidencia |
|---|---|---|---|---|---|
| Codificación segura (OWASP Top 10, ASVS) | Matthew | En estudio autodidacta; sin capacitación oficial | 2026-11-19 (inicio) | — | Aplicación de ASVS 5.0 en E0-05, E0-13 y E0-16 |
| Manejo de datos de tarjeta y PIN (PCI) | Matthew | En estudio autodidacta; sin capacitación oficial | 2026-11-19 (inicio) | — | Librerías PCI SSS/SLC y mapeo PCI↔ASVS en CISO Assistant |
| Protección de datos personales (LOPDP) | Eli | En estudio autodidacta; sin capacitación oficial | 2026-11-19 (inicio) | — | — |
| Uso responsable de asistentes de IA | Eli | En estudio autodidacta; sin capacitación oficial | 2026-11-19 (inicio) | — | — |

Pendiente: cada responsable completa una capacitación formal de su tema y la registra aquí (fecha, duración y
certificado). Mientras tanto, el responsable de cada tema es la referencia del equipo para revisar las historias
que lo tocan.

Cada persona del equipo completa los cuatro temas antes de trabajar en historias de dinero, tarjetas o seguridad, y
los repasa una vez por año.

## Revisión al final de cada fase

Al cerrar cada fase (épica) el responsable revisa: inventarios (01–03), plazos de vulnerabilidades abiertas (04),
modelos de amenazas de los módulos tocados, excepciones vigentes y registro de capacitación. El resultado se anota en el
issue de la épica.

## Excepción: base compartida que también es producción (P4-11)

- **Situación:** hay una sola base (Azure SQL `enquohub`) que usan desarrollo, pruebas de integración y producción.
- **Riesgo:** una migración o una prueba defectuosa afecta datos reales; no hay separación de entornos (PCI E-223,
  E-236 · ASVS 15.2.3).
- **Controles compensatorios:**
  - Ensayo de cada migración en una copia restaurada antes de la base compartida, con respaldo previo (**E0-02**).
  - Respaldo diario cifrado fuera de Azure y procedimiento de restauración probado (**E0-02**).
  - Migraciones solo con el ejecutor y el login administrativo, nunca con el de la aplicación (**E0-01**).
  - Pruebas de integración con reversión obligatoria (**E0-11**).
  - Aprobación del responsable antes de cada ejecución real.
- **Aprobada por:** `hugo-chicaiza`.
- **Revisión:** antes de la **primera entrega externa** (E11-01). En esa revisión se decide separar la base de
  producción o renovar la excepción con fecha nueva.

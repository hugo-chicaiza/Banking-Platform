# Seguridad del ciclo de vida (E0-16)

Primera versión, que **cada historia actualiza** cuando agrega un dato, una clave, una herramienta o una superficie.
Responsable de la evidencia: `hugo-chicaiza` (decisión P4-5).

| Documento | Contenido | Criterio |
|---|---|---|
| [01-activos-sensibles.md](01-activos-sensibles.md) | Datos, recursos y funciones sensibles: clasificación, dónde viven, retención, flujos y protección | ASVS 14.1.1, 14.1.2 · PCI E-012 a E-050 |
| [02-inventario-claves.md](02-inventario-claves.md) | Cada clave y secreto: propósito, algoritmo, longitud, origen y rotación; el offset 3DES como excepción | ASVS 11.1.1, 11.1.2 · PCI E-192 a E-197 |
| [03-herramientas-digitales.md](03-herramientas-digitales.md) | Herramientas (incluidos asistentes de IA), uso previsto y control de lo que producen | PCI E-222 a E-236 |
| [04-politica-seguridad.md](04-politica-seguridad.md) | Reporte, tratamiento, plazos de corrección por severidad, aviso a clientes | ASVS 15.1.1 · PCI E-204 a E-206 |
| [05-modelo-amenazas-plantilla.md](05-modelo-amenazas-plantilla.md) | Plantilla de modelo de amenazas por módulo | — |
| [06-modelo-amenazas-seguridad-organizacion.md](06-modelo-amenazas-seguridad-organizacion.md) | Primer modelo: seguridad (sesión, roles, permisos) y organización | — |
| [07-gobierno.md](07-gobierno.md) | Roles y responsabilidades, registro de capacitación, revisión por fase, excepción de la base compartida (P4-11) | PCI E-223, E-236 · ASVS 15.2.3 |

Relacionado: [inventario de registros](../inventario-registros.md) (E0-13).

**Regla de mantenimiento:** una historia que agrega un dato personal o de tarjeta, una clave, una dependencia de terceros,
una herramienta o un endpoint expuesto actualiza el documento correspondiente en el mismo pull request.

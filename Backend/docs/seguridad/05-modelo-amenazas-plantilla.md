# 05 · Plantilla de modelo de amenazas (por módulo)

Copiar como `06-modelo-amenazas-<modulo>.md` y completarlo en la primera historia del módulo; cada historia que agregue
un endpoint, un dato sensible o una integración lo actualiza.

```markdown
# Modelo de amenazas · <Módulo>

- **Versión / fecha / autor:**
- **Historias que cubre:**

## 1. Alcance
Qué hace el módulo, quién lo usa (roles), qué endpoints expone y con qué otros módulos o servicios habla.

## 2. Activos
| Activo | Clase (C1–C4) | Dónde vive | Ver inventario |

## 3. Diagrama de flujo de datos
Actores, procesos, almacenes y **límites de confianza** (navegador ↔ Worker ↔ backend ↔ base / WorkOS / HSM).

## 4. Amenazas (STRIDE)
| Id | Categoría | Amenaza | Componente | Probabilidad | Impacto | Riesgo | Control existente | Control pendiente (issue) |
Categorías: Suplantación, Manipulación, Repudio, Divulgación, Denegación de servicio, Elevación de privilegios.

## 5. Casos de abuso del dominio
Fraude interno, doble gasto, salto de aprobación, acceso a otra agencia, manipulación de montos, reintentos.

## 6. Requisitos derivados
ASVS / PCI SSS que aplican, con su prueba.

## 7. Riesgos aceptados
Qué se acepta, quién lo aprueba y hasta cuándo.
```

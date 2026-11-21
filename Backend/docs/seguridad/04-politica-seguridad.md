# 04 · Política de seguridad

## Reporte

- **Interno:** cualquier miembro del equipo abre un issue con la etiqueta `seguridad` (sin datos reales ni secretos en
  el texto) o, si es sensible, avisa directo al responsable de seguridad (`hugo-chicaiza`).
- **Externo:** a la dirección de contacto de seguridad de la institución. Se acusa recibo en **2 días hábiles**.
- Nadie publica el detalle de una vulnerabilidad abierta.

## Severidad

Se usa la puntuación CVSS v3.1 del aviso (dependencias) o la estimación del equipo (hallazgos propios), ajustada por el
contexto: una falla que expone datos C4 (tarjeta, PIN, sesión) sube un nivel.

| Severidad | CVSS | Plazo de corrección | Mientras tanto |
|---|---|---|---|
| Crítica | 9.0 – 10.0 | **7 días** | Mitigación el mismo día (deshabilitar la función, regla en el proxy) |
| Alta | 7.0 – 8.9 | **30 días** | Mitigación si es explotable desde internet |
| Media | 4.0 – 6.9 | **90 días** | — |
| Baja | 0.1 – 3.9 | **180 días** o en la siguiente versión | — |

**Uso en el pipeline de dependencias:** `pip-audit` y `npm audit` fallan el CI ante cualquier vulnerabilidad conocida.
Una excepción solo se acepta con issue `seguridad` que indique la severidad, el motivo (p. ej. sin versión corregida o
no alcanzable) y la fecha límite de esta tabla; vencido el plazo, la excepción se retira y el CI vuelve a fallar.

## Tratamiento

1. Confirmar y clasificar (severidad, datos afectados, alcance).
2. Contener (mitigación) y corregir con prueba que reproduzca la falla (regresión).
3. Revisar la corrección (pull request con revisión de una segunda persona en dinero, seguridad, criptografía y
   migraciones) y desplegar.
4. Registrar en el issue: causa, corrección, fechas y evidencia; actualizar inventarios y el modelo de amenazas.

## Aviso a clientes y autoridades

Si un incidente compromete datos de clientes (C3 o C4), el responsable informa a la institución en **24 horas** para que
ella notifique a los titulares y a la autoridad según la LOPDP y la normativa de la SEPS. El equipo entrega el
informe técnico: qué datos, cuántos titulares, desde cuándo, qué se hizo.

## Revisión

Esta política se revisa al final de cada fase (ver [gobierno](07-gobierno.md)) y ante cada incidente.

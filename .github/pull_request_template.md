<!--
  Plantilla de pull request — F-02 (#16)

  El objetivo es que quien revise sepa en 30 segundos qué cambió, por qué y
  cómo comprobarlo. Si una sección no aplica, se escribe «No aplica» y por qué;
  borrarla deja la duda de si se olvidó.
-->

## Qué cambia

<!-- Dos o tres frases. Qué hace el PR, no qué archivos toca: eso ya está en el diff. -->

## Issue

<!--
  `Closes #16` cierra el issue y mueve la tarjeta del tablero al integrar.
  Usar `Refs #16` si el PR es solo una parte de la historia.
-->
Closes #

## Por qué así

<!--
  La parte que el diff no cuenta: qué alternativas se descartaron y por qué.
  Es lo que evita que en tres meses alguien «simplifique» algo que estaba así
  a propósito. Si el cambio es evidente, basta una línea.
-->

## Cómo comprobarlo

<!--
  Pasos concretos para que quien revise lo reproduzca. No «probar que funciona».

  Ejemplo:
    1. cd Backend && uvicorn app.main:app --reload
    2. curl -i http://127.0.0.1:8000/health
    3. Comprobar que la respuesta lleva X-Request-Id y Cache-Control: no-store
-->

## Verificación local

<!-- Marcar solo lo que de verdad se ejecutó. Una casilla marcada sin ejecutar
     es peor que una sin marcar: hace que quien revise confíe en algo que no pasó. -->

- [ ] Backend: `ruff format --check . && ruff check . && mypy && pytest`
- [ ] Frontend: `npm run verify`
- [ ] No aplica (el PR no toca código)

## Seguridad

<!-- Estas tres son las que importan en una aplicación que mueve dinero. -->

- [ ] No se añade ninguna credencial, token, `.env` ni certificado al repositorio
- [ ] Ningún dato sensible (contraseña, PIN, PAN, cédula) llega a un log, a una
      URL ni a un mensaje de error
- [ ] Toda consulta nueva a la base usa parámetros enlazados, nunca cadenas
      interpoladas

<!--
  Si alguna de estas tres no se cumple, explicar aquí por qué y qué mitigación
  se aplica. No se integra sin esa explicación.
-->

## Tipo de cambio

- [ ] `feat` — funcionalidad nueva
- [ ] `fix` — corrección de un defecto
- [ ] `chore` — mantenimiento, dependencias o configuración
- [ ] `docs` — documentación
- [ ] `test` — pruebas
- [ ] `refactor` — reorganización sin cambio de comportamiento
- [ ] `ci` — integración continua

## Impacto en otras historias

<!--
  Qué desbloquea y a quién afecta. Ejemplo:
    - Desbloquea F-04: `errors.py` deja la base de ProblemDetails.
    - Afecta a F-05: el frontend ya tiene los tres entornos configurados.
-->

## Antes de pedir revisión

- [ ] La rama sigue la convención de [`CONTRIBUTING.md`](../CONTRIBUTING.md)
- [ ] El título del PR está en formato Conventional Commits
- [ ] El CI está en verde
- [ ] El PR es de una sola historia; si cubre varias, está dividido

<!--
  Recordatorio para quien revise:
  Aprobar un PR es asumir que se entendió lo que hace. Si algo no se entiende,
  preguntarlo es parte de la revisión, no una molestia. Revisar el diff
  completo, no solo el resumen.
-->

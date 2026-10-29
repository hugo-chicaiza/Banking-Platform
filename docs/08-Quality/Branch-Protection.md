# Protección de `main` y `develop`

Documento de F-02 ([#16](https://github.com/hugo-chicaiza/Banking-Platform/issues/16)),
criterio de aceptación «`main` protegida: una rama por historia y PR revisado».

**Esto no se puede configurar desde un pull request.** La protección de rama es
un ajuste del repositorio y requiere permiso de administración. Este documento
dice exactamente qué aplicar y por qué; quien administre el repositorio
([@hugo-chicaiza](https://github.com/hugo-chicaiza)) lo aplica una vez.

## Qué proteger

| Rama | Qué es | Nivel |
| --- | --- | --- |
| `main` | Código estable, lo que se despliega a producción | Estricto |
| `develop` | Integración de historias terminadas | Moderado |

`develop` se protege menos a propósito: es donde se integra a diario, y un
proceso demasiado pesado ahí hace que la gente busque atajos. El rigor va donde
está el riesgo.

## Opción A — Ruleset (recomendada)

Los *rulesets* son el mecanismo actual de GitHub. Frente a las *branch
protection rules* clásicas: se pueden importar desde un archivo, versionar, y
dejan registro de quién los cambió.

### Importar

**Settings → Rules → Rulesets → New ruleset → Import a ruleset** y subir
[`ruleset-main.json`](ruleset-main.json).

### Aplicar a mano

**Settings → Rules → Rulesets → New branch ruleset**

| Ajuste | Valor | Por qué |
| --- | --- | --- |
| Ruleset name | `Proteccion main` | — |
| Enforcement status | **Active** | En `Evaluate` solo informa; no bloquea nada. |
| Target branches | `main` (Default branch) | — |
| Restrict deletions | **sí** | Borrar `main` por accidente es recuperable, pero caro. |
| Block force pushes | **sí** | Un `--force` sobre `main` reescribe el historial y deja a todo el equipo con un clon inválido. |
| Require linear history | **sí** | Con *squash* a `main`, el historial queda como una lista legible de lo que se entregó. |
| Require a pull request before merging | **sí** | Es el criterio de aceptación: nada entra sin revisión. |
| → Required approvals | **1** | Con un equipo de este tamaño, 2 bloquearía el avance. Lo que importa es que no sea 0. |
| → Dismiss stale approvals | **sí** | Una aprobación sobre un commit anterior no aprueba el código nuevo. Sin esto, se aprueba un PR y después se le añade cualquier cosa. |
| → Require review from Code Owners | **sí** (ver nota) | Un cambio en el CI o en la configuración de seguridad no lo integra quien lo escribió. |
| → Require conversation resolution | **sí** | Evita integrar con comentarios abiertos sin responder. |
| → Allowed merge methods | **Squash** solo | Un commit por historia. |
| Require status checks to pass | **sí** | — |
| → Require branches up to date | **sí** | Dos PR que pasan por separado pueden romper juntos. |
| → Checks requeridos | ver abajo | — |
| Block creations | no | — |
| Require deployments to succeed | no | Lo gestiona el entorno `production`. |

> **Nota sobre Code Owners.** Antes de activarlo hay que confirmar que las
> personas de [`.github/CODEOWNERS`](../../.github/CODEOWNERS) tienen permiso de
> **escritura** en el repositorio. Si no lo tienen, GitHub ignora la regla en
> silencio y queda la impresión de que el control está puesto. Si hay dudas,
> activar primero el resto y esta regla después.

### Verificaciones obligatorias

Exactamente estas cuatro, por su nombre:

```
Backend Quality and Security
Frontend CI
Convenciones de rama y título
Contenido del PR
```

Dos aclaraciones sobre estos nombres, porque no son arbitrarios:

**`Backend Quality and Security`** es el nombre del job único de
`backend-ci.yml`. Ese workflow corre en **todo** PR, sin filtro de ruta: cada
paso comprueba por su cuenta si hay algo que analizar, así que siempre devuelve
un resultado real en lugar de omitirse.

**`Frontend CI`** es el **job agregador** del final de `frontend-ci.yml`: tiene
`if: always()` y `needs: [todos los demás]`, y evalúa el resultado de cada uno
traduciendo «omitido» a éxito de forma explícita.

Esto resuelve un problema real: `frontend-ci.yml` sí usa filtros por ruta, así
que un PR que solo toca el backend **omite** sus jobs. Si se marcaran los jobs
individuales como obligatorios, GitHub contaría esos jobs omitidos como
satisfechos y la verificación pasaría sin haber corrido nada — que es
exactamente el agujero que tenía la configuración anterior con el filtro
`startsWith(github.head_ref, ...)`.

Con el job agregador, el resultado es explícito y auditable en su log.

**Los nombres tienen que coincidir carácter por carácter** con el `name:` del
job en el YAML. Si no coinciden, GitHub espera para siempre un check que nunca
llega y el PR queda bloqueado sin explicación.

> Los checks solo aparecen en la lista desplegable de GitHub después de haberse
> ejecutado **al menos una vez**. Secuencia: integrar el PR de F-02 → dejar que
> el CI corra una vez → volver aquí y añadirlos.

## Ruleset de `develop`

Mismo procedimiento, con estos cambios:

| Ajuste | Valor en `develop` | Por qué la diferencia |
| --- | --- | --- |
| Target branches | `develop` | — |
| Required approvals | **1** | Igual: la revisión es donde está el valor. |
| Require linear history | **no** | Se integra con *merge commit* para conservar los commits de cada historia. |
| Allowed merge methods | **Merge** y **Squash** | — |
| Require review from Code Owners | **no** | Demasiado pesado para la integración diaria. |
| Checks requeridos | los mismos cuatro | — |

## Opción B — Branch protection rules clásicas

Si los rulesets no están disponibles: **Settings → Branches → Add branch
protection rule**, patrón `main`, y marcar:

- [x] Require a pull request before merging
  - [x] Require approvals: **1**
  - [x] Dismiss stale pull request approvals when new commits are pushed
  - [x] Require review from Code Owners
- [x] Require status checks to pass before merging
  - [x] Require branches to be up to date before merging
  - [x] Los cuatro checks de arriba
- [x] Require conversation resolution before merging
- [x] Require linear history
- [x] Do not allow bypassing the above settings
- [ ] Allow force pushes — **desactivado**
- [ ] Allow deletions — **desactivado**

## Qué NO se configura, y por qué

| Ajuste | Decisión | Motivo |
| --- | --- | --- |
| Require signed commits | No, por ahora | Obliga a todo el equipo a configurar GPG o SSH con firma. Merece la pena si el proyecto pasa a manejar dinero real; hoy, el coste de arranque es mayor que el beneficio. |
| Required approvals: 2 | No | Con un equipo de este tamaño y plazos de sprint, bloquearía el avance. Se revisa si el equipo crece. |
| Restrict who can push | No | La regla de PR obligatorio ya lo cubre. |
| Lock branch | No | `main` tiene que poder avanzar. |

Las decisiones están aquí para que se puedan discutir, no para cerrarlas.

## Comprobar que funciona

Después de aplicarlo:

```shell
git switch main
git pull
echo "prueba" >> README.md
git commit -am "test: comprobar la proteccion de rama"
git push
```

Esperado:

```
! [remote rejected] main -> main (protected branch hook declined)
```

Deshacer:

```shell
git reset --hard origin/main
```

Si el push **funciona**, la protección no está activa. Revisar que el
*enforcement status* del ruleset sea `Active` y no `Evaluate`.

## Y si hay que saltarse la protección

Pasa: una urgencia en producción a las 11 de la noche.

**Forma correcta:** rama `hotfix/<nombre>`, PR, y pedir a quien administre el
repositorio que apruebe. El CI tarda cinco minutos y es justo cuando más
conviene que corra.

**Si de verdad hay que forzarlo**, quien administre puede hacerlo —GitHub lo
registra en el audit log— y después:

1. Abrir un issue describiendo qué se saltó y por qué.
2. Abrir un PR con la prueba que debería haber detectado el problema.

Un bypass sin ese seguimiento convierte la excepción en costumbre.

## Estado

- [ ] Ruleset de `main` aplicado y en `Active`
- [ ] Ruleset de `develop` aplicado
- [ ] Los cuatro checks obligatorios añadidos (tras la primera ejecución del CI)
- [ ] Permisos de los Code Owners confirmados
- [ ] Protección verificada con un push de prueba rechazado

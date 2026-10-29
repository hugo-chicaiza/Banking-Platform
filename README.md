# Banking-Plataform

## Main branches

| Branch    | Purpose                                   | Merge strategy |
| --------- | ----------------------------------------- | -------------- |
| `main`    | Stable, production-ready code             | Squash merge   |
| `develop` | Integration branch for completed features | Merge commit   |

## Commit Convention

Use Conventional Commits to keep commit messages consistent and descriptive.

| Type       | Use for                                     |
| ---------- | ------------------------------------------- |
| `feat`     | New feature                                 |
| `fix`      | Bug fix                                     |
| `chore`    | Maintenance, dependencies, or configuration |
| `docs`     | Documentation                               |
| `test`     | Tests                                       |
| `refactor` | Code cleanup without behavior changes       |

## Branch naming conventions

| Area          | Convention                        | Example                       |
| ------------- | --------------------------------- | ----------------------------- |
| Backend       | `feat/backend-<issue>-<name>`  | `feat/backend-1-createClient` |
| Frontend      | `feat/frontend-<issue>-<name>` | `feat/frontend-2-login`       |
| QA            | `test/<name>`                     | `test/flow-1-back2Front`      |
| Documentation | `docs/<name>`                     | `docs/update-1-roadmap`       |

### Work on the module

Stage and commit your changes.

```
git add .
git commit -m "feat: implement Add Client"
```


### Push the branch

```
git push -u origin feat/backend-1-createClient
```

---

## Backend conventions

Full structure and rules: [`Backend/TreeFolderStructure.md`](Backend/TreeFolderStructure.md).

- **One folder per module** (`app/modules/<module>/`) with its own `router.py`, `schemas.py`, `repository.py`, and `service.py` only if it has business rules. Shared code lives in `app/core/`.
- **One file per layer per module.** Add your endpoints to the existing files of the module; never create parallel files.
- **Split by sub-domain, not by size of the endpoint list.** Only when a module has sub-topics with their own rules (e.g. `creditos/solicitudes/`, `creditos/pagos/`) or a file passes ~400-500 lines.
- **A module calls another module's `service`, never its `repository`.**
- **Each value in one place:** environment values in `.env` / `core/config.py`, shared values as constants in `core/`.

### Run the CI checks locally (before pushing)

From the repository root, with `Backend/.venv` created (`py -3.14 -m venv Backend/.venv` and `Backend/.venv/Scripts/python -m pip install -r Backend/requirements-dev.txt`):

```
Backend/.venv/Scripts/ruff format Backend          # fix formatting
Backend/.venv/Scripts/ruff check Backend --fix     # lint and auto-fix
Backend/.venv/Scripts/pyright --pythonpath Backend/.venv/Scripts/python.exe Backend
Backend/.venv/Scripts/python -m pytest Backend/tests
Backend/.venv/Scripts/python -m bandit -q -r Backend -x Backend/tests,Backend/.venv
```

## Getting Started

See `backend/README.md` and `frontend/README.md`
for setup and execution instructions.

## Collaboration

1. Create a feature branch.
2. Make and test your changes.
3. Open a pull request into `main`.

## Documentation

Start with `docs/Home.md`.

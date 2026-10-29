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

## Getting Started

See `backend/README.md` and `frontend/README.md`
for setup and execution instructions.

## Collaboration

1. Create a feature branch.
2. Make and test your changes.
3. Open a pull request into `main`.

## Documentation

Start with `docs/Home.md`.

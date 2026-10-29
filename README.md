# Banking Platform

Banking platform for a credit union (cooperativa de ahorro y crédito): clients,
accounts, cards, ATM transactions, loans, teller/vault reconciliation and
accounting.

| | |
| --- | --- |
| Backend | FastAPI (Python 3.14) |
| Frontend | Angular 22 (TypeScript 6) |
| Database | SQL Server — `CooperativaDB` + `SeguridadDB` |
| Board | [Banking Platform Project](https://github.com/users/hugo-chicaiza/projects/4) |

## Quick start

```shell
git clone https://github.com/hugo-chicaiza/Banking-Platform.git
cd Banking-Platform
git switch develop

# 1. Local SQL Server (set MSSQL_SA_PASSWORD in .env first)
cp .env.example .env
docker compose up -d sqlserver db-init

# 2. Backend  → http://127.0.0.1:8471
cd Backend
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload

# 3. Frontend → http://localhost:4200
cd ../Frontend
npm ci
npm start
```

Full, step-by-step instructions — including the ODBC driver and the common
failure modes — are in
**[`docs/06-Development/Setup-Guide.md`](docs/06-Development/Setup-Guide.md)**.

## Repository layout

```text
Banking-Platform/
├── Backend/                  # FastAPI API
├── Frontend/                 # Angular app           → Frontend/README.md
├── db/init/                  # Schema + seed scripts (F-07, F-08)
├── docs/                     # Technical docs        → docs/Home.md
├── GitHubProject_Files/      # Backlog: epics, stories, endpoint specs (Obsidian)
├── .github/workflows/        # CI and deployment
├── docker-compose.yml        # Local SQL Server + OpenAPI mock
└── sonar-project.properties  # SonarQube configuration
```

> `docs/` holds **technical** documentation (how to set up, configure and
> deploy). `GitHubProject_Files/` holds the **backlog**, synced with Obsidian
> and the project board. A story spec goes in the latter; a setup guide in the
> former.

## Documentation

| Document | What it covers |
| --- | --- |
| [docs/Home.md](docs/Home.md) | Documentation index |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branches, commits, pull requests, review |
| [SECURITY.md](SECURITY.md) | What never enters the repo; what to do if a secret leaks |
| [Frontend/README.md](Frontend/README.md) | Frontend structure, commands, environments |
| [Setup Guide](docs/06-Development/Setup-Guide.md) | Local setup from scratch |
| [Quality Gates](docs/08-Quality/Quality-Gates.md) | What CI checks, with which thresholds and why |
| [Branch Protection](docs/08-Quality/Branch-Protection.md) | Exact `main`/`develop` protection settings |

## Main branches

| Branch | Purpose | Merge strategy |
| --- | --- | --- |
| `main` | Stable, production-ready code. Deploys to **production**. | Squash merge |
| `develop` | Integration branch for completed features. Deploys to **staging**. | Merge commit |

Both are protected: no direct pushes, PR with one approval and green CI
required. See [Branch Protection](docs/08-Quality/Branch-Protection.md).

## Branch naming

| Area | Convention | Example |
| --- | --- | --- |
| Backend | `feat/backend-<issue>-<name>` | `feat/backend-50-create-client` |
| Frontend | `feat/frontend-<issue>-<name>` | `feat/frontend-21-base-layout` |
| Infrastructure, CI, configuration | `chore/<issue>-<name>` | `chore/16-setup-environments-ci` |
| QA | `test/<name>` | `test/atm-deposit-flow` |
| Documentation | `docs/<name>` | `docs/update-roadmap` |
| Fix | `fix/<name>` | `fix/late-fee-rounding` |
| Production hotfix | `hotfix/<name>` | `hotfix/session-never-expires` |

Enforced by CI
([`pr-governance.yml`](.github/workflows/pr-governance.yml)).

## Commit convention

[Conventional Commits](https://www.conventionalcommits.org/). The **PR title**
must follow the same format: merges into `main` are squashed, so the PR title is
what ends up in the history.

| Type | Use for |
| --- | --- |
| `feat` | New feature |
| `fix` | Bug fix |
| `chore` | Maintenance, dependencies, or configuration |
| `docs` | Documentation |
| `test` | Tests |
| `refactor` | Code cleanup without behaviour changes |
| `perf` | Performance improvement |
| `ci` | Continuous integration |

## Workflow

```shell
git switch develop && git pull
git switch -c feat/backend-50-create-client

# ... work ...

# Run the same checks CI runs, before pushing
cd Backend && ruff format --check . && ruff check . && mypy && pytest
cd Frontend && npm run verify

git add .
git commit -m "feat(backend): add client registration endpoint"
git push -u origin feat/backend-50-create-client
```

Then open a pull request **into `develop`** (only releases and hotfixes target
`main` directly), fill in the template, and move the board card to
**Ready for QA** once it is merged.

Board rule (F-06): **nothing reaches Done without passing through Ready for QA.**

Details in [CONTRIBUTING.md](CONTRIBUTING.md).

## Project status

Epic 0 — Foundation ([#13](https://github.com/hugo-chicaiza/Banking-Platform/issues/13)):

| Story | Scope | Status |
| --- | --- | --- |
| [F-01](https://github.com/hugo-chicaiza/Banking-Platform/issues/15) | OpenAPI contract + mock server | Open |
| [F-02](https://github.com/hugo-chicaiza/Banking-Platform/issues/16) | Project setup, environments, CI | **In progress** (part 1 of 2) |
| [F-03](https://github.com/hugo-chicaiza/Banking-Platform/issues/17) | JWT authentication and roles | Open |
| [F-04](https://github.com/hugo-chicaiza/Banking-Platform/issues/20) | Standard error format and audit trail | Open |
| [F-05](https://github.com/hugo-chicaiza/Banking-Platform/issues/21) | Base layout and role-based routing | Open |
| [F-06](https://github.com/hugo-chicaiza/Banking-Platform/issues/22) | Unit test strategy and test data | Open |
| [F-07](https://github.com/hugo-chicaiza/Banking-Platform/issues/107) | Seed data and catalogues | Open |
| [F-08](https://github.com/hugo-chicaiza/Banking-Platform/issues/108) | Database gap migration | Open |
| [F-09](https://github.com/hugo-chicaiza/Banking-Platform/issues/109) | Catalogue API | In progress |

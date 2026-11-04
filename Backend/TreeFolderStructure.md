```mermaid
treeView-beta
backend/
├── app/
│   ├── main.py                    # Creates FastAPI, adds middlewares, includes each module's router
│   ├── core/                      # Shared code, no business logic. One folder per concern, no loose files
│   │   ├── config/
│   │   │   └── settings.py        # Settings from .env (pydantic-settings)
│   │   ├── database/
│   │   │   ├── db.py              # 2 engines: CooperativaDB and SeguridadDB; connection per request
│   │   │   └── uow.py             # (planned) "Unit of work": one DB transaction per money operation
│   │   ├── security/
│   │   │   ├── auth.py            # require\_auth (WorkOS JWT, F-03), require\_roles("CAJERO", ...)
│   │   │   └── audit.py           # Writes Auditoria.Auditoria (F-04)
│   │   └── api/                   # HTTP layer shared by every router
│   │       ├── schemas.py         # CamelModel (snake_case ↔ camelCase JSON), Money (Decimal → JSON number)
│   │       ├── errors.py          # ProblemDetails + map THROW 5xxxx → HTTP/code (F-04 table)
│   │       ├── middleware.py      # X-Request-Id → traceId
│   │       ├── rate_limit.py      # Requests per minute and IP → 429
│   │       ├── idempotency.py     # (planned) registroUnico handling (Idempotent-Replay)
│   │       └── pagination.py      # (planned) page, pageSize ≤ 100, sort → {items, page, pageSize, total}
│   │
│   ├── modules/
│   │   ├── auth/                  # M0 · AUT-01..11 (SeguridadDB)
│   │   │   ├── router.py          # HTTP only: routes, status codes, Depends(require\_roles)
│   │   │   ├── schemas.py         # Pydantic request/response models (= openapi.yaml)
│   │   │   ├── service.py         # Business rules, decisions, transaction handling
│   │   │   └── repository.py      # SQL / stored procedure calls only
│   │   ├── catalogos/             # M0 · CAT-01..10 · read-only: router + schemas + repository (no service)
│   │   ├── clientes/              # M1 · CLI-01..14
│   │   ├── cuentas/               # M2 · CTA-01..09
│   │   ├── tarjetas/               # M2 · TAR-01..06
│   │   ├── atm/                   # M3 · ATM-01..17
│   │   ├── transacciones/         # M3 · TRX-01..03 + shared autorizar/aplicar movimiento
│   │   ├── creditos/              # M4 · CRE-01..27
│   │   │   └── amortizacion.py    # Pure math: French/German plans (easy to unit test)
│   │   ├── caja/                  # M5 · CAJ-01..18
│   │   ├── boveda/                # M5 · BOV-01..06
│   │   └── contabilidad/          # M6 · CON-01..07 + AC-01 asientos (internal service, no router)
│   │
│   └── integrations/
│       └── buro.py                # Simulated credit bureau client (replace with a real one later)
│
├── tests/
│   ├── unit/                      # Pure logic, no DB (e.g. amortizacion.py)
│   └── integration/               # Router → service → repository against a test DB
│
├── .env.example                   # Copy to .env; in Azure use App Settings
├── requirements.in                # Runtime dependencies (edit this)
├── requirements.txt               # Generated lock with hashes (Azure installs it)
├── requirements-dev.in            # Tests + CI tools (edit this)
└── requirements-dev.txt           # Generated dev lock with hashes (CI installs it)
```

> Rule: a module may call another module's `service`, never its `repository`.
>
> Rule: `service.py` lives inside each module and exists only when the module has business rules;
> read-only modules (e.g. `catalogos`) go router → repository.
>
> Rule: every router declares `dependencies=[Depends(require_auth)]`; auth is implemented once in
> `core/security/auth.py`.
>
> Rule: every router uses the F-04 error format: `APIRouter(..., route_class=ProblemDetailsRoute,
> responses=RESPUESTAS_ERROR)` from `core/api/errors.py`.
>
> Rule: `core/` has no loose files. A new shared file goes in the folder of its concern (`config/`, `database/`,
> `security/`, `api/`); create a new folder only for a new concern.
>
> Rule: a value defined in one place only. Environment-dependent values (DB names, servers, ports, keys) go in
> `.env` / `core/config/settings.py`; values shared by several modules (e.g. `/api/v1`, role names) go as constants
> in the matching `core/` folder; values used by a single module stay in that module.

### Imports from `core/`

Branches created before 2026-11-03 still use the old paths and must update them before merging:

| Before | Now |
|---|---|
| `from app.core.config import ...` | `from app.core.config.settings import ...` |
| `from app.core.db import ...` | `from app.core.database.db import ...` |
| `from app.core.security import require_auth` | `from app.core.security.auth import require_auth` |
| `from app.core import audit` | `from app.core.security import audit` |
| `from app.core.schemas import ...` | `from app.core.api.schemas import ...` |
| `from app.core.errors import ...` | `from app.core.api.errors import ...` |
| `from app.core.middleware import ...` | `from app.core.api.middleware import ...` |
| `from app.core.rate_limit import ...` | `from app.core.api.rate_limit import ...` |
>
> Rule: one `router.py`, `schemas.py`, `repository.py` (and `service.py` if needed) per module. Every developer adds
> their endpoints to those files; never create parallel files (`router_cat02.py`). Split a module into sub-folders only
> by sub-domain with its own rules (e.g. `creditos/solicitudes/`, `creditos/pagos/`) or when a file passes ~400-500
> lines, never by endpoint count.


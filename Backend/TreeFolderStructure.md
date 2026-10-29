```mermaid
treeView-beta
backend/
├── app/
│   ├── main.py                    # Creates FastAPI, adds middlewares, includes each module's router
│   ├── core/                      # Shared code, no business logic
│   │   ├── config.py              # Settings from .env (pydantic-settings)
│   │   ├── db.py                  # 2 engines: CooperativaDB and SeguridadDB; connection per request
│   │   ├── uow.py                 # "Unit of work": one DB transaction per money operation
│   │   ├── security.py            # require\_auth (WorkOS JWT, F-03), require\_roles("CAJERO", ...)
│   │   ├── schemas.py             # CamelModel (snake_case ↔ camelCase JSON), Money (Decimal → JSON number)
│   │   ├── errors.py              # ProblemDetails + map THROW 5xxxx → HTTP/code (F-04 table)
│   │   ├── audit.py               # Writes Auditoria.Auditoria
│   │   ├── middleware.py          # X-Request-Id → traceId, request logging (masks PAN/PIN)
│   │   ├── idempotency.py         # registroUnico handling (Idempotent-Replay)
│   │   └── pagination.py          # page, pageSize ≤ 100, sort → {items, page, pageSize, total}
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
├── requirements.txt               # Runtime (Python 3.14)
└── requirements-dev.txt           # Tests + CI tools
```

> Rule: a module may call another module's `service`, never its `repository`.
>
> Rule: `service.py` lives inside each module and exists only when the module has business rules;
> read-only modules (e.g. `catalogos`) go router → repository.
>
> Rule: every router declares `dependencies=[Depends(require_auth)]`; auth is implemented once in `core/security.py`.
>
> Rule: a value defined in one place only. Environment-dependent values (DB names, servers, ports, keys) go in
> `.env` / `core/config.py`; values shared by several modules (e.g. `/api/v1`, role names) go as constants in `core/`;
> values used by a single module stay in that module.
>
> Rule: one `router.py`, `schemas.py`, `repository.py` (and `service.py` if needed) per module. Every developer adds
> their endpoints to those files; never create parallel files (`router_cat02.py`). Split a module into sub-folders only
> by sub-domain with its own rules (e.g. `creditos/solicitudes/`, `creditos/pagos/`) or when a file passes ~400-500
> lines, never by endpoint count.


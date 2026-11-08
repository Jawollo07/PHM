# PHM — Pelican Host Manager

A self-hosted customer and billing platform for Pelican Panel.

## Product direction

PHM supports commercial game-server hosting and privately assigned servers. Every customer has exactly one prepaid wallet. Customers top up that wallet using supported payment providers or manually verified payments; purchases and renewals debit the same balance.

## Architecture

- Backend: FastAPI (Python 3.12+)
- Database: PostgreSQL (SQLAlchemy 2 + Alembic)
- Background jobs: Redis + worker (planned)
- Frontend: React + TypeScript (planned)
- Pelican integration: server-side adapter using Pelican's documented API
- Deployment: Docker Compose

## Wallet invariants

1. Exactly one wallet per customer, enforced by a database uniqueness constraint.
2. Balances are integer EUR cents; floating-point money is never used.
3. Every mutation creates an immutable ledger row and updates the cached balance in the same DB transaction.
4. Ledger amounts are signed: credits are positive, debits are negative.
5. Top-ups and refunds must be credits; purchases must be debits. Admin adjustments may go either way.
6. Debits cannot overdraw the wallet.
7. A repeated idempotency key with the same payload returns the original transaction; a different payload is rejected.
8. Payment-provider funds are credited only after server-side verification. Pending top-ups are not spendable.

There are no separate balances for payment methods, products, subscriptions, or promotions.

## Local development

Requirements: Python 3.12+ and PostgreSQL 16+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export DATABASE_URL="postgresql+asyncpg://phm:change-me@localhost:5432/phm"
alembic upgrade head
uvicorn backend.app.main:app --reload
```

Run checks:

```bash
ruff check backend
pytest -q
alembic upgrade head
```

For a local database, `docker compose up -d db` starts PostgreSQL. Set a strong `POSTGRES_PASSWORD` in the environment before using Compose outside a disposable local environment.

## Development status

The initial single-wallet ledger, signed transaction semantics, Alembic schema migration, wallet tests, and GitHub Actions CI are in place. Authentication, payment-provider verification, customer UI, Pelican provisioning, and production deployment hardening remain future milestones.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/ROADMAP.md](docs/ROADMAP.md), and [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md).

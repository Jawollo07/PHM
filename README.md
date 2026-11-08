# PHM — Pelican Host Manager

A self-hosted customer and billing platform for Pelican Panel.

## Product direction

PHM supports commercial game-server hosting and privately assigned servers. Every customer has exactly one prepaid wallet. Customers top up that wallet using supported payment providers or manually verified payments; purchases and renewals debit the same balance.

## Architecture

- Backend: FastAPI (Python)
- Database: PostgreSQL
- Background jobs: Redis + worker (planned)
- Frontend: React + TypeScript (planned)
- Pelican integration: server-side adapter using Pelican's documented API
- Deployment: Docker Compose

## Wallet invariants

1. One wallet per customer.
2. Balances are stored as integer cents (EUR), never floating point.
3. All wallet mutations are immutable ledger entries.
4. Credits are only applied after verified payment confirmation or an audited admin adjustment.
5. Debits are atomic and cannot overdraw the wallet.
6. External payment events are idempotent.

## Development status

This repository is being initialized. The first implementation milestone is the backend foundation and wallet ledger. Payment-provider integrations, the customer UI, provisioning, and native Pelican UI integration are added in later milestones.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

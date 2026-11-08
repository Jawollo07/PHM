# PHM Architecture

## Scope

PHM is a customer and commerce platform for a Pelican-based hosting business. It supports paid hosting and privately assigned servers. The commercial model uses exactly one prepaid wallet per customer.

## System boundaries

- PHM owns customer profiles, catalog, orders, wallet ledger, payments, subscriptions, tickets, audit events, and customer-facing authorization.
- Pelican remains the system of record for game-server runtime state, allocations, nodes, eggs, and Wings operations.
- PHM communicates with Pelican only through a server-side API adapter. Pelican credentials must never reach browsers or customers.
- Payment providers are authoritative for external payment status. PHM credits wallets only after verifying provider signatures and payment state.

## Initial stack

- FastAPI + SQLAlchemy 2 async
- PostgreSQL + Alembic migrations
- Redis for future background jobs
- React + TypeScript frontend (future milestone)
- Docker Compose for development and deployment

## Wallet model

Each customer has exactly one row in `wallets`, enforced by a unique `customer_id`. The balance is an integer number of EUR cents. Every mutation creates an immutable `wallet_transactions` row and updates the cached balance in the same database transaction.

Ledger amounts are signed: top-ups and refunds are positive credits; purchases are negative debits; admin adjustments may be positive or negative. Database constraints reject zero amounts, unsupported transaction types, invalid transaction directions, negative resulting balances, and non-EUR wallets.

The unique key `(wallet_id, idempotency_key)` prevents duplicate mutations. Reusing a key with an identical payload returns the original entry; reusing it with a different payload raises an explicit conflict. PostgreSQL row-level locking serializes mutations to a wallet.

No separate balances, bonus wallets, or payment-method-specific balances are permitted. A pending payment is not a wallet credit.

## Security requirements

- Customer authentication and authorization are required before exposing wallet endpoints.
- Admin adjustments require an explicit reason and an audit event.
- Provider webhook signatures and provider-side payment status must be verified before crediting.
- Secrets are environment-only and never committed.
- Use HTTPS in production, secure cookies, CSRF protection where cookie auth is used, rate limits, and audit logging.
- Do not store card details. Use provider-hosted checkout/tokenization.
- Never trust a client-supplied amount for a confirmed payment.

## Planned domain modules

1. Identity and customer profiles
2. Catalog, plans, and configurable products
3. Orders and checkout
4. Single-wallet ledger and top-ups
5. Payment provider adapters (PayPal, Stripe, manual)
6. Subscription/renewal scheduler funded from the same wallet
7. Pelican provisioning adapter
8. Customer portal and admin console
9. Support, notifications, audit, exports

## Provisioning flow

A paid order is created as pending. PHM reserves/debits the wallet atomically when the order is confirmed, then dispatches a provisioning job. The job creates or assigns the Pelican server using the least-privileged server-side credential. The operation is idempotent and records the Pelican server identifier. Failures are retried or compensated through an explicit refund ledger entry; balance changes are never silently deleted.

## Current implementation

The repository currently contains the initial signed wallet ledger, the Alembic schema revision, wallet-domain tests, and a GitHub Actions workflow that runs linting, tests, and a PostgreSQL migration check. Authentication, provider verification, UI, Pelican provisioning, and production deployment hardening remain future milestones.

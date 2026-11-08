# PHM — Complete Product & Delivery Plan

Planning baseline: 8 November 2026. This document is the product and engineering baseline for Jawollo07/PHM. A task is complete only when implemented, tested, and documented.

## 1. Product vision

PHM (Pelican Host Manager) is a self-hosted customer, commerce, and operations platform for a game-server hosting business using Pelican Panel. It supports both commercial customers who buy hosting and private customers who receive free or manually assigned servers.

PHM provides a standalone customer portal and admin console, a backend API, background workers, and a controlled Pelican integration. A native Pelican in-panel entry point is optional and must use an officially supported extension mechanism. The standalone portal remains functional if the native integration is unavailable.

## 2. Non-negotiable business rules

### One wallet per customer
Every customer has exactly one EUR wallet. No separate balances for subscriptions, payment methods, promotions, products, or top-ups.
- Money is integer cents, never floating point.
- Every mutation creates an immutable ledger entry.
- Credits require verified payment settlement or an audited administrator adjustment.
- Debits are atomic and cannot create a negative balance.
- Duplicate webhooks/jobs cannot duplicate credits or charges.
- Purchases, renewals, refunds, and corrections all use this same wallet.
- Payment method is transaction metadata, never a separate wallet.
- Wallet transfers between customers are out of scope initially.
- Pending top-ups are not spendable.

### Wallet-first commerce
Customers add money to the wallet and spend the available balance on products and services. PayPal, Stripe, and manual payments fund the wallet. Product checkout debits the wallet; it does not charge the payment provider directly.

### Paid and private server assignments
Each server assignment has a source: paid order, private/admin assignment, or migration/import. Private assignments may be free and have no renewal schedule, but use the same customer account, server inventory, permissions, and audit trail.

### System ownership
PHM owns customers, catalog, orders, wallet, accounting records, subscriptions, support, and business entitlements. Pelican owns nodes, allocations, eggs, runtime configuration, and Wings/container operations. PHM stores Pelican identifiers and limited synchronized metadata, not a duplicate Pelican runtime database.

## 3. Roles and permissions

- Guest: public catalog, registration, login, password reset.
- Customer: own profile, wallet, top-ups, transactions, orders, invoices/receipts, assigned servers, tickets.
- Support agent: customer lookup and tickets; no wallet adjustment or secret access by default.
- Billing staff: payment review, accounting documents, wallet adjustments with explicit permission and audit.
- Server operator: server assignment, provisioning retries, suspend/unsuspend; no payment secrets.
- Administrator: customer, product, role, and operational management.
- Owner/super-admin: sensitive settings, integration credentials, role grants, high-risk actions.

Use deny-by-default RBAC. Enforce authorization in backend services, not just frontend controls. Require staff 2FA and recent re-authentication for privileged operations.

## 4. Customer portal

### Account
Email-verified registration, login/logout, secure sessions, password reset, optional customer 2FA, profile/contact details, session management, security history, data export, and account deletion request workflow subject to legally required retention.

### Wallet
One balance overview in EUR; configurable top-up minimum/maximum; provider checkout; manual bank-transfer request with unique reference; ledger history with date/type/description/reference/resulting balance. Pending top-ups are clearly marked and never spendable. Customers cannot edit balances or ledger entries.

### Catalog and orders
Categories, products, plans, billing intervals, availability, configurable RAM/CPU/disk/backups/egg limits, add-ons, order review, wallet-only checkout, insufficient-funds handling, order history, cancellation requests, and capacity validation before accepting an order.

### Servers
List all assigned servers with name, product, status, allocation, and renewal date when applicable. Link safely to Pelican or use supported account linking/SSO if available. Never expose Wings credentials or proxy arbitrary console commands. Paid/private assignment types are visible but do not create separate customer accounts.

### Support and notifications
Tickets with categories, priority, attachments, replies, status, and staff assignment. Email and in-portal notifications for account, payment, order, provisioning, renewal, and ticket events, plus preferences and delivery logs.

## 5. Admin console

Customer search/profiles/status/roles/audit; wallet and immutable ledger; audited manual credit/debit/refund; payment review; product/plan/add-on/coupon management; orders/cancellations/refunds/renewals; Pelican node/egg/allocation mapping and capacity; server assignment/provision/retry/suspend/unsuspend/terminate; support inbox; sales/top-up/wallet-liability/active-server/renewal reports; provider/email settings; maintenance mode; audit search/export.

Wallet adjustments, credential changes, server termination, and role escalation require explicit confirmation and audit logging. Dual approval for large adjustments can be added.

## 6. Wallet, payments, purchases, and renewals

### Ledger
Wallet row stores current balance; append-only ledger is the accounting history. Each entry records wallet, transaction type, signed cents, resulting balance, idempotency key, reference, actor/source, description, and timestamp.

Transaction types: topup, purchase, renewal, refund, admin_credit, admin_debit, chargeback_adjustment. Never edit/delete posted entries; correct with compensating entries. Mutations use a single DB transaction, wallet row lock, and unique idempotency constraint. Check sufficient funds under lock. Repeated idempotency keys return the original result without another mutation.

### Top-up lifecycle
created → pending → paid_verified → credited, or failed/cancelled/expired/review_required.
1. Create intent using server-calculated amount/currency.
2. Redirect to provider-hosted checkout or show bank-transfer instructions.
3. Verify webhook signature and provider-side payment status.
4. Validate amount, currency, merchant account, provider transaction ID, and ownership.
5. Record provider event idempotently.
6. Credit the single wallet exactly once.
7. Notify customer and create applicable accounting document.

Never credit from a browser redirect or client-supplied status.

### Providers
PayPal hosted checkout + signed webhooks; Stripe hosted checkout + signed webhooks; manual payments with pending/review/approved/rejected states. Provider-specific logic is isolated behind adapters.

### Spending and refunds
Validate price, availability, eligibility, and wallet funds. Wallet debit and order transition are atomic. Provisioning runs asynchronously after order commit. Permanent provisioning failure creates a compensating refund credit; original entries remain. Chargebacks/provider reversals create review cases. Never silently permit negative balance.

### Renewals
Subscriptions are schedules, not separate wallets. Renewal debits the same wallet. Notify before renewal, validate service/price, debit idempotently, extend only after successful debit. Insufficient funds trigger notices, configurable grace period, then Pelican suspension. Do not automatically delete data as the first response to non-payment.

### Legal/accounting
Before real-money launch obtain German/EU legal and tax review for consumer information, VAT/pricing, invoices/receipts, cancellation/withdrawal, prepaid balance treatment, provider terms, privacy, retention, and bookkeeping. Software features alone do not establish compliance.

## 7. Pelican integration

Use documented Pelican APIs and stable supported extension points only. Keep Application API credentials server-side with least privilege. Never expose API tokens, daemon tokens, Wings credentials, or node secrets to browsers. Use a dedicated PHM service identity where possible. Store Pelican IDs and sync status. Provisioning must be idempotent and retryable. Treat timeouts as unknown outcomes until reconciled; do not blindly create duplicate servers.

### Paid provisioning
1. Validate order and wallet funds.
2. Atomically debit wallet and write an outbox/provisioning event.
3. Select eligible node/allocation based on capacity and product rules.
4. Create/map Pelican user.
5. Create server with egg, image, startup, environment, limits, and allocation.
6. Persist Pelican server ID and metadata.
7. Reconcile status and show server in portal.
8. Retry safely; on terminal failure, refund via compensating ledger entry.

### Private assignment
Authorized operator selects customer and existing/new Pelican server, records assignment type private, and grants access using Pelican's supported user/subuser mechanism. No wallet debit unless a priced service is explicitly attached.

### Native Pelican UI
Verify the target Pelican release's official plugin/extension API and lifecycle first. Do not invent a manifest or patch core files. If no stable supported extension exists, provide a portal link or separately maintained integration package.

## 8. Technical architecture

Start as a modular monolith, not microservices.
- web: React + TypeScript customer portal/admin console.
- api: FastAPI REST API and domain services.
- worker: provisioning, payment reconciliation, email, renewals.
- scheduler: renewal/reconciliation schedules.
- db: PostgreSQL.
- redis: queue/cache/rate-limit support.
- reverse proxy/TLS: host-provided.

Backend domains: identity, customers, wallet, payments, catalog, orders, subscriptions, servers, Pelican, support, notifications, audit, admin.

Stack: Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Redis/task queue, React/TypeScript, Docker Compose, OpenAPI. Keep the repository's FastAPI direction; do not introduce a second backend framework.

## 9. Core data model

users; customer_profiles; roles; permissions; user_roles; role_permissions; wallets (unique customer_id); wallet_transactions (append-only signed ledger); topups; payment_events; products; plans; plan_versions; plan_limits; addons; orders; order_items; order_events; subscriptions; servers (assignment type and Pelican ID); pelican_nodes; pelican_eggs; allocation_inventory; tickets; ticket_messages; ticket_attachments; notifications; email_delivery_logs; audit_logs; outbox_events.

Use foreign keys, unique/check constraints, indexes, timestamps, and explicit state enums. Snapshot purchased product name, price, tax treatment, and limits in order items so catalog changes never rewrite history.

## 10. API surface

- /api/v1/auth/* — register, login, logout, email verification, password reset, sessions, 2FA.
- /api/v1/me — profile/preferences.
- /api/v1/wallet — balance and ledger.
- /api/v1/topups — create/inspect top-up intents.
- /api/v1/webhooks/paypal and /api/v1/webhooks/stripe — verified provider events.
- /api/v1/catalog/* — public products/plans.
- /api/v1/orders/* — create/inspect orders.
- /api/v1/servers/* — own server assignments and permitted actions.
- /api/v1/tickets/* — support.
- /api/v1/admin/* — staff-only operations.
- /api/v1/integrations/pelican/* — internal adapter operations.

Use pagination, stable error formats, request IDs, idempotency keys for mutations, and explicit API versioning.

## 11. Security, privacy, reliability

Argon2id; secure HttpOnly/SameSite sessions; email verification; rate limiting/brute-force protection; session revocation; mandatory staff 2FA; least-privilege RBAC; CSRF protection for cookie auth; strict CORS/CSP; validation and upload restrictions; secrets only in environment/secret storage; encrypt integration credentials at rest with separately managed key; verify webhooks and reconcile provider state; audit privileged actions and wallet changes; PostgreSQL/upload backups and restore drills; structured logs, health/readiness endpoints, metrics, alerts; tested migrations and restore procedures; retention/deletion policies reviewed legally.

## 12. Deployment and operations

Safe .env.example only; private container networking; expose only reverse-proxy-facing ports; pin tested images (no latest in production); health checks/restart policies; persistent DB/upload volumes; separate dev/staging/prod config; document DNS/TLS/reverse proxy/SMTP/payment webhooks/Pelican credentials/backups/upgrades/rollback/restore. Run migrations as controlled release steps. Provide protected initial-admin bootstrap command.

## 13. Phased implementation and acceptance criteria

### Phase 0 — Engineering baseline
- [x] Initialize repository, architecture, initial roadmap.
- [x] FastAPI skeleton and health endpoint.
- [x] Initial SQLAlchemy wallet models/mutation primitive.
- [ ] Correct and test ledger sign/type representation.
- [ ] Add Ruff, pytest, CI, dependency lock strategy.
- [ ] Add Alembic and initial migrations.
Acceptance: clean checkout builds; migrations apply to empty PostgreSQL; lint/tests pass in CI.

### Phase 1 — Identity and customers
- [ ] Customer/profile schema and migrations.
- [ ] Registration, email verification, login/logout, password reset.
- [ ] Secure sessions and revocation.
- [ ] RBAC and protected staff bootstrap.
- [ ] Customer/admin API and security tests.
Acceptance: customers can access only their own data; backend tests prove permission boundaries.

### Phase 2 — Wallet and top-up intents
- [ ] Exactly one wallet per customer, created automatically.
- [ ] Atomic credit/debit/refund/admin adjustment.
- [ ] Append-only ledger and idempotency.
- [ ] Concurrency tests prove no overdraft/duplicate posting.
- [ ] Top-up state machine; pending funds never spendable.
- [ ] Mandatory reason and audit for admin adjustment.
Acceptance: every balance change is ledger-backed; concurrent tests pass; second wallet creation is rejected.

### Phase 3 — Payment methods
- [ ] Provider adapter interface.
- [ ] PayPal checkout and signed webhook verification.
- [ ] Stripe checkout and signed webhook verification.
- [ ] Manual payment request and staff review.
- [ ] Event deduplication, reconciliation, failure handling.
Acceptance: each method credits the same wallet once after verified settlement; redirects cannot credit funds.

### Phase 4 — Catalog and orders
- [ ] Categories, products, plans, limits, add-ons.
- [ ] Versioned price/plan snapshots.
- [ ] Order validation and wallet checkout.
- [ ] Coupon validation and usage limits.
- [ ] Order lifecycle, cancellation, refunds.
Acceptance: wallet-only checkout; historical order totals remain reproducible.

### Phase 5 — Pelican and provisioning
- [ ] Confirm supported Pelican API version/permissions.
- [ ] Adapter with timeout, retry, reconciliation.
- [ ] Node/egg/allocation mapping and capacity checks.
- [ ] Pelican user mapping and server creation.
- [ ] Provisioning queue/outbox and idempotency.
- [ ] Private server assignment/access grant.
- [ ] Suspension, unsuspension, termination safeguards.
Acceptance: paid test order creates exactly one server; private assignment makes no wallet debit; failures reconcile or refund safely.

### Phase 6 — Customer portal
- [ ] Responsive registration/login/account.
- [ ] Wallet, top-up, ledger, payment status.
- [ ] Catalog, plan details, checkout, order history.
- [ ] Server list and safe Pelican links.
- [ ] Profile, security, tickets, notifications.
Acceptance: mobile/desktop customer journeys work without admin data leakage.

### Phase 7 — Admin and support
- [ ] Customer search/detail.
- [ ] Wallet/payment review and audited adjustments.
- [ ] Catalog, orders, subscriptions, server operations.
- [ ] Tickets, staff assignment, notification templates.
- [ ] Audit search and reports.
Acceptance: normal operations do not require direct database edits.

### Phase 8 — Renewals and lifecycle
- [ ] Renewal scheduler using the same wallet.
- [ ] Customer notices and grace period.
- [ ] Insufficient-funds handling and Pelican suspension.
- [ ] Retry/reconciliation/refund/restore workflows.
Acceptance: jobs are idempotent across restarts and never double-charge.

### Phase 9 — Native Pelican integration
- [ ] Verify official extension mechanism for target Pelican release.
- [ ] Build only against supported interfaces.
- [ ] Add panel link/embedded view where feasible.
- [ ] Compatibility matrix and standalone fallback.
Acceptance: no core patching; disabling integration does not break PHM.

### Phase 10 — Production readiness
- [ ] Threat model and security review.
- [ ] End-to-end top-up/purchase/provision/refund/renewal tests.
- [ ] Load tests for wallet concurrency and webhook bursts.
- [ ] Backup/restore and upgrade/rollback drills.
- [ ] Monitoring, alerting, logs, incident runbooks.
- [ ] German/EU legal and tax review before real-money launch.
Acceptance: staging checklist passes and operator can deploy, back up, restore, upgrade, and troubleshoot from docs.

## 14. Testing strategy

Unit tests for domain services, money calculations, state machines, permissions. PostgreSQL integration tests for constraints, row locks, concurrency, idempotency. Provider contract tests with signed fixtures and sandbox accounts. Pelican adapter tests with mocks and a non-production panel. API authorization/validation tests. Browser end-to-end tests. Failure cases include duplicate/delayed webhook, provider timeout, Pelican timeout after successful create, worker crash, duplicate job, insufficient funds, and refund retry. Never use production Pelican or live payment credentials for automated tests.

## 15. Delivery rules

Work in small feature branches and PRs. Each PR includes migrations, tests, docs, and rollback notes where relevant. Do not merge a phase until acceptance criteria pass. Keep secrets and real customer data out of Git. Do not call PHM production-ready until wallet concurrency, payment verification, provisioning reconciliation, backups, security, and legal review are complete.

## 16. Immediate next tasks

1. Correct the initial wallet implementation: signed ledger amounts consistently, constrained transaction types, safe idempotency collision handling.
2. Add Alembic migrations and PostgreSQL integration test infrastructure.
3. Add CI for lint, unit, and integration tests.
4. Implement identity/customer schema and authentication.
5. Expose wallet APIs only after concurrency and ledger tests pass.

This plan is the product baseline. Changes to the one-wallet rule or paid/private customer model require explicit documentation and review.

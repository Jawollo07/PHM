# PHM — Pelican Host Manager

A Django-based customer and billing platform for managing hosting services backed by Pelican Panel.

PHM is under active development. The repository now contains verified private-customer authentication, an administrator-managed hosting catalog, wallet-funded customer checkout, signed wallet accounting and opt-in recurring subscriptions. Invoice issuance and automatic server allocation remain incomplete. Verified PHM customers are now automatically created or matched and linked as Pelican panel users.

## Product scope

PHM supports **private customers only**. There are no business accounts, company tenants or customer-member roles.

Each registered user is provisioned with one personal customer account and one wallet belonging to that customer. The customer account holds contact information, addresses and customer-specific preferences.

Customers will be able to purchase and renew hosting services using their wallet and view their transactions, orders, invoices and assigned servers. Administrators manually credit or debit customer wallets and may assign privately managed servers to customers. Online top-ups, payment methods, payment providers and payment processing are explicitly out of scope.

## Technology and current state

| Area | Current state / direction |
|---|---|
| Backend | Python and Django |
| Authentication | Django authentication with a custom `User` model |
| Database | SQLite in the current development settings; PostgreSQL is intended for production |
| Frontend | No complete frontend architecture established in the current repository |
| Hosting integration | Pelican Application API user creation/linking implemented; server allocation remains pending |
| Payments | No payment providers, payment methods or online top-ups; administrators make manual wallet adjustments only |
| Deployment | Production configuration pending |

The Django project is located in `backend/`. Its project package is `backend/core/`, and Django applications are located in `backend/apps/`.

## Current Django applications

### `apps.auth`

Owns user identity and authentication. The current custom user model uses a username for login and stores a unique email address. Registration creates a personal customer, profile, settings and wallet atomically. Email verification uses one-time tokens whose SHA-256 hashes are stored in the database. Unverified users cannot log in. Password reset links are sent only to verified email addresses.

### `apps.customers`

Owns the personal customer account associated one-to-one with a Django user. It currently contains:

- `Customer`: customer status and contact phone number;
- `CustomerAddress`: contact and billing addresses;
- `CustomerSettings`: customer-specific notification preferences. Language and timezone are stored in `UserProfile`.

There are no business-account or customer-membership models. The account page reads and updates customer information. New users are provisioned with a customer, user profile, notification settings and wallet in one database transaction.

### `apps.catalog`

Contains administrator-managed hosting products and plans. Prices and setup fees are stored as integer EUR cents. Billing intervals are configurable (one-time, day, week, month or year), and resource limits are stored as structured JSON without assuming a specific hosting platform. Active offers are exposed through the authenticated customer catalog.

### `apps.orders`

Contains wallet-funded order creation and the customer checkout flow. Placing a paid order reserves wallet funds through a hold; confirming payment captures the hold and writes a signed purchase transaction. Cancelling an unpaid order releases the reservation. Free plans can be ordered without creating a zero-value ledger entry. Order items preserve immutable product, plan, price, billing interval and resource snapshots. Customers can browse active catalog entries, purchase with their wallet and view only their own orders. Automated server provisioning is still pending.

### `apps.wallet`

Owns the single EUR wallet for each personal customer. The repository includes wallet, hold, signing-key, transaction and checkpoint models, idempotent transaction services, administrator-only manual adjustments, a read-only searchable ledger admin and signed checkpoint support. `verify_ledger` checks every wallet hash/signature chain, the latest checkpoint against the live ledger and the optional external checkpoint archive. Private signing keys are loaded from a protected file or legacy environment configuration and are not stored in the PHM database. SQLite and PostgreSQL triggers now reject direct UPDATE/DELETE operations on transactions and checkpoints. The external archive detects database rollback or key-registry changes if it is stored with separate access controls; production secret management and deployment hardening are still outstanding.

### `apps.subscriptions`

Recurring orders create a subscription snapshot after successful wallet payment. Billing intervals use calendar-aware day, week, month and year arithmetic. Automatic renewal is **disabled by default** and requires explicit customer opt-in. Renewals debit only the customer's PHM wallet; insufficient funds move the subscription to `past_due` without creating a debit. Customers can disable renewal or schedule cancellation at the end of the paid period. `process_subscription_renewals` processes due contracts. Automatic service suspension and notifications are not enabled yet.

### Planned domain applications

The following areas remain planned and are not yet complete:
- `invoices`: immutable invoice documents, legally compliant numbering and tax handling;
- `pelican`: synchronization and provisioning through the Pelican Panel API;
- `audit`: security-sensitive and administrative audit events;
- `notifications`: customer email and in-app notifications.

## Wallet and accounting rules

These are mandatory domain invariants for the wallet implementation:

1. Exactly one wallet per customer.
2. Store money as integer EUR cents. Never use floating-point values for money.
3. Purchases, renewals, refunds and administrator adjustments affect the same wallet. Wallet funding is manual and administrator-controlled.
4. Every posted balance change must create a corresponding ledger entry in the same database transaction.
5. Ledger entries are append-only. Corrections are represented by compensating entries, not by editing history.
6. Credits are positive and debits are negative.
7. A debit must never make the wallet balance negative.
8. Idempotency keys prevent duplicate processing. Reusing a key with a different request payload must be rejected.
9. Wallet credits are created only by authorized administrator adjustments; no customer-facing top-up or payment workflow is implemented or planned.
10. Wallet operations must be serialized safely to prevent concurrent requests from overspending a balance.

A cryptographically verifiable ledger is a design goal. Hashes and signatures must be generated and verified by dedicated ledger services. A signature alone does not replace database access controls, backups or externally retained checkpoints.

## Repository layout

```text
PHM/
├── backend/
│   ├── core/
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── asgi.py
│   │   └── wsgi.py
│   ├── apps/
│   │   ├── auth/
│   │   ├── customers/
│   │   ├── catalog/
│   │   ├── wallet/
│   │   ├── orders/
│   │   └── subscriptions/
│   └── manage.py
└── README.md
```

This is the current high-level layout, not a promise that every planned application or production component already exists.

## Local development

The Django project entry point is `backend/manage.py`. From the repository root:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
```

Install the backend dependencies, then run Django checks and inspect/apply migrations:

```bash
python -m pip install -r requirements.txt
python manage.py check
python manage.py showmigrations
python manage.py migrate
python manage.py test
python manage.py checkpoint_ledger
python manage.py verify_ledger
```

Start the development server:

```bash
python manage.py runserver
```

The current settings use SQLite for development. Do not expose the development server publicly or use the current settings as a production configuration.

## Configuration and security

Before deploying PHM:

- load `SECRET_KEY` from a secret manager or environment variable;
- set `DEBUG=False`;
- configure `ALLOWED_HOSTS` and trusted CSRF origins;
- configure PostgreSQL and database credentials outside source control;
- configure secure HTTPS cookies and proxy headers for the actual reverse-proxy setup;
- configure a real email backend;
- remove password, token and payment-data logging;
- apply least-privilege database permissions;
- add tests for authorization, customer isolation, wallet concurrency and payment idempotency;
- establish encrypted backups and a tested restore procedure.

Never commit passwords, private signing keys, API tokens, production database credentials or other secrets. Configure `PELICAN_PANEL_URL` with the HTTPS base URL of the Pelican panel and `PELICAN_APPLICATION_API_TOKEN` with a least-privilege Application API token. Optionally set `PELICAN_API_TIMEOUT` (default: 10 seconds). The token must be stored in the deployment secret manager or protected environment file, never in source control. PHM provisions Pelican users after the PHM email address is verified. The Application API must be reachable from the PHM backend. Password synchronization requires permission to read and update the linked Pelican users. A Pelican account is assigned no server automatically yet; server provisioning is a separate next phase. Configure `WALLET_LEDGER_KEY_ID`, `WALLET_LEDGER_SIGNER` and `WALLET_LEDGER_PRIVATE_KEY_FILE` (path to a protected PEM file) before using ledger signing or checkpoint commands. Set `WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE` to an append-only archive path on storage outside the database, with separate access controls and backups. For an existing installation, first verify the live database with `verify_ledger`, then run `python manage.py bootstrap_checkpoint_archive` to establish the trusted external baseline. The bootstrap trusts the database state at that moment; do it only after confirming that state is known-good. Set `WALLET_LEDGER_AUTO_CHECKPOINT=true` to synchronously create a signed checkpoint after each new ledger transaction or wallet created by personal-customer provisioning. The database commit precedes the archive write; if that write fails, the request reports an error and further automatic wallet changes fail closed until the archive is repaired. Each checkpoint verifies the existing checkpoint chain, wallet signatures and trusted signing-key registry, so it scans ledger history and may add latency as the ledger grows. Direct SQL edits bypass automatic signing and are unsupported; ledger inconsistencies, database rollback and key-registry changes are detected by `verify_ledger`. Signing-key registry changes require an explicit controlled re-anchoring/rotation procedure. Run `verify_ledger` regularly. With automatic checkpointing disabled, run `checkpoint_ledger` after valid ledger activity changes the snapshot; it verifies the existing checkpoint signatures and chain before creating another checkpoint.

The external archive is signed and written after the database commit, so an archive-signer or filesystem failure cannot undo that commit. Once the signer or destination is corrected, use `python manage.py sync_checkpoint_archive` to append the verified committed checkpoint suffix.

Prefer setting `WALLET_LEDGER_PRIVATE_KEY_FILE` to the path of an unencrypted Ed25519 PEM private-key file or a 128-character hexadecimal Ed25519 key. Restrict the file permissions to the service account (`chmod 600`); only the file path, not the key material, needs to be in the environment. The legacy `WALLET_LEDGER_PRIVATE_KEY_B64` and `WALLET_LEDGER_PRIVATE_KEY_HEX` inputs are still supported, but configure exactly one key source. Never commit a private key.

Protect the checkpoint archive independently from the database: use a restricted directory and preferably a separate host, volume or WORM-backed location. The application creates the archive file with mode `0600`. On a new installation, create the first signed checkpoint with the archive path configured before enabling automatic checkpoints. After an interrupted archive write, `python manage.py sync_checkpoint_archive` appends only a signature-verified database suffix; it refuses database rollback, ledger mismatch or a changed signing-key registry. If the external archive is ahead of the database, restore a trusted database backup rather than rebuilding the archive from the database.

For the legacy 128-character hexadecimal format, `WALLET_LEDGER_PRIVATE_KEY_HEX` must encode 64 bytes: a 32-byte private seed followed by its matching 32-byte public key.

## Development status

PHM is an early-stage Django application. The current repository should be treated as a development scaffold, not as a production-ready hosting platform. Online payments are intentionally excluded; wallet funding is administrator-managed. A GitHub Actions workflow now runs Django checks, migration consistency checks and the backend test suite on pushes and pull requests.

Verify model/migration history before applying schema changes to a database containing data. The authentication and customer migration history has been extended to provision personal customer records and wallets. Always back up an existing database before applying migrations, and verify the migration plan against a copy first.

## Scheduled operations

The repository includes systemd unit templates under `deploy/systemd/`:

- `phm-ledger-integrity.timer`: verifies the signed ledger daily at 04:00 Europe/Berlin.
- `phm-subscription-renewals.timer`: processes subscription renewals daily at 04:15 Europe/Berlin. Only subscriptions for which the customer explicitly enabled automatic renewal are charged.

Before installing, adjust `User`, `Group`, `WorkingDirectory`, the virtualenv path and `EnvironmentFile` in both service units to the actual deployment. Create the first signed ledger anchor once with `python manage.py checkpoint_ledger`; the daily verifier requires an existing checkpoint. Then install the units, run `systemctl daemon-reload` and enable the timers with `systemctl enable --now phm-ledger-integrity.timer phm-subscription-renewals.timer`. Check execution with `systemctl list-timers` and `journalctl -u phm-ledger-integrity.service -u phm-subscription-renewals.service`.

These are deployment templates only. They are not activated on a server by committing them to the repository.

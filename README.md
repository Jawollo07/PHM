# PHM — Pelican Host Manager

A Django-based customer and billing platform for managing hosting services backed by Pelican Panel.

PHM is under active development. The repository contains the Django project, authentication, personal-customer account provisioning and an initial wallet ledger/service foundation. Payment processing, hosting orders, subscriptions, invoices and Pelican provisioning are not yet integrated into a complete end-to-end product.

## Product scope

PHM supports **private customers only**. There are no business accounts, company tenants or customer-member roles.

Each registered user is provisioned with one personal customer account and one wallet belonging to that customer. The customer account holds contact information, addresses and customer-specific preferences.

Customers are intended to be able to top up their wallet through supported payment providers or manually verified payments, purchase and renew hosting services using the same wallet, and view their transactions, orders, invoices and assigned servers. Administrators may also assign privately managed servers to customers.

## Technology and current state

| Area | Current state / direction |
|---|---|
| Backend | Python and Django |
| Authentication | Django authentication with a custom `User` model |
| Database | SQLite in the current development settings; PostgreSQL is intended for production |
| Frontend | No complete frontend architecture established in the current repository |
| Hosting integration | Pelican Panel API adapter planned |
| Payments | Provider-based and manually verified payments planned |
| Deployment | Production configuration pending |

The Django project is located in `backend/`. Its project package is `backend/core/`, and Django applications are located in `backend/apps/`.

## Current Django applications

### `apps.auth`

Owns user identity and authentication. The current custom user model uses a username for login and stores a unique email address. The app also contains user-profile and email-verification models.

### `apps.customers`

Owns the personal customer account associated one-to-one with a Django user. It currently contains:

- `Customer`: customer status and contact phone number;
- `CustomerAddress`: contact and billing addresses;
- `CustomerSettings`: customer-specific notification preferences. Language and timezone are stored in `UserProfile`.

There are no business-account or customer-membership models. The account page reads and updates customer information. New users are provisioned with a customer, user profile, notification settings and wallet in one database transaction.

### `apps.wallet`

Owns the single EUR wallet for each personal customer. The repository now includes wallet, hold, signing-key, transaction and checkpoint models, initial migrations, idempotent transaction services, and a verification hook for the per-wallet hash/signature chain. The signing operation is injected through a provider callback; private signing keys are not stored in the PHM database. A production signing provider, externally retained checkpoints, database-level append-only enforcement and payment integration are still outstanding.

### Planned domain applications

The following areas remain planned and are not yet complete:
- `payments`: payment-provider integrations, manual payment verification and webhook handling;
- `catalog`: hosting products, plans and prices;
- `orders`: customer purchases;
- `subscriptions`: recurring hosting contracts and renewals;
- `invoices`: invoice creation and records;
- `pelican`: synchronization and provisioning through the Pelican Panel API;
- `audit`: security-sensitive and administrative audit events.

## Wallet and accounting rules

These are mandatory domain invariants for the wallet implementation:

1. Exactly one wallet per customer.
2. Store money as integer EUR cents. Never use floating-point values for money.
3. All top-ups, purchases, renewals, refunds and administrator adjustments affect the same wallet.
4. Every posted balance change must create a corresponding ledger entry in the same database transaction.
5. Ledger entries are append-only. Corrections are represented by compensating entries, not by editing history.
6. Credits are positive and debits are negative.
7. A debit must never make the wallet balance negative.
8. Idempotency keys prevent duplicate processing. Reusing a key with a different request payload must be rejected.
9. Pending top-ups are not spendable. Funds are credited only after server-side payment verification succeeds.
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
│   │   └── wallet/
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

Never commit passwords, private signing keys, API tokens, production database credentials or other secrets.

## Development status

PHM is an early-stage Django application. The current repository should be treated as a development scaffold, not as a production-ready billing or hosting platform.

Verify model/migration history before applying schema changes to a database containing data. The authentication and customer migration history has been extended to provision personal customer records and wallets. Always back up an existing database before applying migrations, and verify the migration plan against a copy first.

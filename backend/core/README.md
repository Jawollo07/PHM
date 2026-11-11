# Django Core

Dieses Verzeichnis enthält die zentrale Django-Projektkonfiguration.

## Dateien

| Datei | Aufgabe |
|---|---|
| `settings.py` | Installierte Apps, Middleware, Datenbank, Auth-Modell, Sprache und statische Dateien |
| `urls.py` | Zentrales URL-Routing für Admin, Authentifizierung und Kundenkonto |
| `asgi.py` | ASGI-Einstiegspunkt |
| `wsgi.py` | WSGI-Einstiegspunkt |

## Aktuelle Einstellungen

- Custom User Model: `accounts.User` aus `apps.auth`.
- Sprache: `de-de`.
- Zeitzone: `Europe/Berlin`.
- Zeitzonenbewusste Datums-/Zeitverarbeitung: aktiviert.
- Entwicklungsdatenbank: SQLite (`backend/db.sqlite3`).
- Django-Admin: `/admin/`.

## URL-Routing

Die zentral eingebundenen Bereiche sind:

- `/admin/` – Django-Administration.
- `/auth/` und `/auth/login/` – Authentifizierung.
- `/auth/logout/` – Logout.
- `/auth/login/test/` – geschützte Testansicht.
- `/account/` – persönliches Kundenkonto.

## Vor Produktivbetrieb zwingend ändern

Die aktuelle Datei enthält Entwicklungswerte (`DEBUG=True`, fest eingetragener unsicherer `SECRET_KEY`, leere `ALLOWED_HOSTS`). Diese Werte dürfen nicht in einer öffentlichen Produktivumgebung verwendet werden. Sie müssen über Umgebungsvariablen oder eine sichere Deployment-Konfiguration gesetzt werden.

Außerdem muss die E-Mail-Konfiguration auf die von Django unterstützten `EMAIL_BACKEND`-/`EMAIL_*`-Einstellungen umgestellt werden. Datenbank, HTTPS, sichere Cookies, CSRF-Trusted-Origins, statische Dateien und Logging sind ebenfalls produktionsgerecht zu konfigurieren.

## App-Registrierung

`INSTALLED_APPS` enthält aktuell `apps.auth` und `apps.customers`, aber noch nicht `apps.wallet`. Die Wallet-App muss vor dem Einsatz mit dem richtigen AppConfig-Modul registriert werden.
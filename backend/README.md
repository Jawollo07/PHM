# Backend

Das PHM-Backend basiert auf Django. Der Django-Projektcode liegt in `core/`, die fachlichen Module in `apps/`.

## Status

| Bereich | Stand |
|---|---|
| Authentifizierung | Django-Custom-User und Login-Views vorhanden |
| Kundenkonto | Persönliches Kundenkonto, Adressen und Einstellungen vorhanden |
| Wallet | Datenmodelle vorhanden; noch keine Ledger-Services oder API-Flows |
| Zahlungen | Noch nicht implementiert |
| Pelican-Integration | Noch nicht implementiert |

Es gibt ausschließlich persönliche Kundenkonten. Ein optionales `company_name` in einer Adresse ist lediglich eine Rechnungs-/Empfängerangabe und kein Geschäftskonto.

## Verzeichnisstruktur

```text
backend/
├── manage.py
├── core/                 # Django-Konfiguration und URL-Routing
└── apps/
    ├── auth/             # Benutzer, Profile, E-Mail-Verifizierung
    ├── customers/        # Kundenkonto, Adressen, Einstellungen
    └── wallet/           # Wallet- und Ledger-Datenmodelle
```

## Lokale Entwicklung

Im Backend-Verzeichnis ausführen:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install Django pycountry
python manage.py check
python manage.py migrate
python manage.py runserver
```

Unter Windows wird die virtuelle Umgebung mit `.venv\\Scripts\\activate` aktiviert. Installiere zusätzlich alle Abhängigkeiten, die im Projekt künftig in einer Dependency-Datei festgeschrieben werden.

## Tests

```bash
cd backend
python manage.py test apps.auth apps.customers
```

Wallet besitzt derzeit noch keine fachlichen Tests. Die vorhandenen Tests decken daher nicht den vollständigen Backendumfang ab.

## Wichtige Konfiguration

Die Einstellungen befinden sich in `core/settings.py`. Die aktuelle Konfiguration ist eine Entwicklungsbasis mit SQLite und `DEBUG=True`; sie ist nicht produktionsbereit. Vor einem Deployment müssen insbesondere Secret Key, `DEBUG`, `ALLOWED_HOSTS`, Datenbank, E-Mail-Backend, HTTPS-/Cookie-Einstellungen und statische Dateien korrekt konfiguriert werden.

`AUTH_USER_MODEL` verweist auf `accounts.User`; das App-Label wird in `apps/auth/apps.py` festgelegt.

## Bekannte Implementierungslücken

- `apps.wallet` ist aktuell nicht in `INSTALLED_APPS` eingetragen. Die Wallet-Modelle werden daher von Django derzeit nicht als installierte App verwaltet.
- Für Wallet-Buchungen, Reservierungen, Signaturen und Checkpoints existieren noch keine Service-Schicht und keine API-Endpunkte.
- Kundenkonto und Wallet werden bei einer Registrierung noch nicht gemeinsam in einem zentralen Registrierungsprozess angelegt.
- Die E-Mail-Konfiguration in `settings.py` verwendet derzeit `MAILERS`; Django erwartet standardmäßig `EMAIL_BACKEND` bzw. `EMAIL_*`-Einstellungen.
- Die Authentifizierungs-Views und URL-Namen benötigen vor einem produktiven Einsatz einen vollständigen Sicherheits- und Funktionstest.

Diese Punkte sind bewusst als aktueller Ist-Stand dokumentiert und nicht als bereits verfügbare Funktionen zu verstehen.
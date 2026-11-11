# Auth-App

Die Auth-App verwaltet die zentrale Benutzeridentität von PHM. Der Python-Paketpfad lautet `apps.auth`; das Django-App-Label ist `accounts`.

## Modelle

- **`User`** – basiert auf `AbstractUser`, verwendet den Benutzernamen als Login-Feld und besitzt eine eindeutige E-Mail-Adresse. Zusätzlich werden E-Mail-Verifizierungsstatus und Zeitstempel gespeichert.
- **`UserProfile`** – optionale Profilangaben wie Anzeigename, Zeitzone und Sprache; One-to-One mit `User`.
- **`EmailVerification`** – Verifizierungsdatensätze mit Zweck, Ablaufzeit und Token-Hash. Das Klartext-Token soll nicht in der Datenbank gespeichert werden.

`AUTH_USER_MODEL` ist auf `accounts.User` gesetzt. Diese Einstellung muss vor den ersten produktiven Migrationen korrekt feststehen.

## Aktuelle Routen

| Route | Zweck |
|---|---|
| `/auth/` | Authentifizierungsseite |
| `/auth/login/` | Login per GET/POST |
| `/auth/logout/` | Logout |
| `/auth/login/test/` | Geschützte Testseite nach erfolgreichem Login |

Die Routen werden derzeit in `core/urls.py` zentral eingebunden.

## Benutzer per CLI anlegen

Aus dem Backend-Verzeichnis:

```bash
python -m apps.auth.cli create-user
```

Der Befehl fragt Benutzername, E-Mail-Adresse und Passwort interaktiv ab und validiert das Passwort anhand der Django-Passwortregeln.

## Tests

```bash
python manage.py test apps.auth
```

Die Tests prüfen unter anderem Login, ungültige Zugangsdaten, Superuser-Erstellung und den CLI-Benutzeranlagepfad.

## Noch offen

- E-Mail-Verifizierung ist als Modell vorbereitet; Versand, Token-Erstellung und Verifizierungs-Endpunkte müssen noch implementiert werden.
- Passwort-Reset und E-Mail-Änderung benötigen vollständige Workflows.
- Login-/Logout-Routen, Redirects, Rate-Limits, CSRF-Verhalten und Session-Sicherheit müssen vor Produktivbetrieb überprüft werden.
- Zugangsdaten dürfen niemals in Logs geschrieben werden. Logs dürfen insbesondere keine Passwörter oder Verifizierungstokens enthalten.
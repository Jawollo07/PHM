# Customers-App

Die Customers-App bildet das persönliche Kundenkonto ab. Sie ist ausdrücklich nicht für Unternehmens-Tenants oder Geschäftskonten gedacht.

## Modelle

### `Customer`

- UUID als Primärschlüssel.
- One-to-One-Beziehung zum konfigurierten Benutzer (`AUTH_USER_MODEL`).
- Telefonnummer und Kundenstatus (`active`, `suspended`, `archived`, `banned`).
- Sperrzeitpunkt und Sperrgrund.

Ein Benutzer kann höchstens ein Kundenkonto besitzen. Das Kundenkonto ist die fachliche Eigentümerinstanz der Wallet.

### `CustomerAddress`

Ein Kundenkonto kann Rechnungs- und Kontaktadressen speichern. Die optionale Angabe `company_name` ist lediglich eine zusätzliche Empfänger-/Rechnungszeile und erzeugt kein Geschäftskonto. Die Datenbank erzwingt höchstens eine Standardadresse je Kundentyp.

### `CustomerSettings`

Speichert Sprache sowie E-Mail-, Service-, Zahlungs-, Sicherheits- und Marketing-Benachrichtigungseinstellungen. Marketing-E-Mails sind standardmäßig deaktiviert.

## Route

`/account/` zeigt das Konto an und erlaubt angemeldeten Benutzern, ihre Benutzer-, Kunden-, Adress- und Benachrichtigungsdaten zu aktualisieren.

Die Speicherung erfolgt in `account_view` innerhalb einer Datenbanktransaktion. Beim Speichern werden Customer und CustomerSettings bei Bedarf angelegt. Eine Wallet wird in diesem Ablauf derzeit noch nicht erzeugt.

## Tests

```bash
python manage.py test apps.customers
```

Die Tests decken unter anderem den Zustand ohne Kundenkonto, das Anzeigen der Telefonnummer, das Aktualisieren von Kontodaten, das Anlegen einer Kontaktadresse und doppelte E-Mail-Adressen ab.

## Abgrenzung

- Benutzername, E-Mail-Adresse und Passwort gehören zum Benutzerkonto in der Auth-App.
- Zeitzone und Anzeigename liegen im `UserProfile` der Auth-App.
- Kundenbezogene Adressen und Benachrichtigungseinstellungen liegen hier.
- Wallet-Guthaben und Buchungen gehören ausschließlich in die Wallet-App.

## Noch offen

- Die Kundenanlage sollte in einen zentralen Registrierungs-/Onboarding-Service verschoben werden.
- Customer, CustomerSettings und Wallet sollen künftig atomar und konsistent angelegt werden.
- Die aktuelle Kontoseite verwendet die erste gespeicherte Adresse; eine vollständige Verwaltung mehrerer Adressen ist noch nicht umgesetzt.
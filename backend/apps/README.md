# Backend-Apps

Dieses Verzeichnis enthält die fachlichen Django-Apps von PHM. Jede App kapselt ihre eigenen Modelle, Views, Formulare, Tests und Migrationen.

## Apps

| App | Zuständigkeit | Aktueller Stand |
|---|---|---|
| [`auth/`](auth/README.md) | Benutzeridentität, Login, Profil und E-Mail-Verifizierung | Grundstruktur vorhanden |
| [`customers/`](customers/README.md) | Persönliches Kundenkonto, Adressen und Einstellungen | Kontoseite und Formulare vorhanden |
| [`wallet/`](wallet/README.md) | Guthaben, Reservierungen und unveränderliches Ledger | Modelle vorhanden, fachliche Services fehlen |

## Architekturregeln

- Ein Benutzer besitzt höchstens ein persönliches Kundenkonto (`User` → `Customer`, One-to-One).
- Ein Kundenkonto soll genau eine Wallet besitzen (`Customer` → `Wallet`, One-to-One).
- Die Wallet gehört zum Kundenkonto, nicht direkt zum Benutzer.
- Es gibt keine Unternehmens-Tenants, Geschäftskonten oder Kundenmitgliedschaften.
- Geldbeträge werden in ganzzahligen Euro-Cent gespeichert.
- Finanzielle Änderungen müssen später ausschließlich über transaktionale Wallet-Services erfolgen; Views sollen keine Kontostände direkt verändern.

## Django-App-Registrierung

Die installierten Apps werden zentral in `backend/core/settings.py` verwaltet. Vor dem Erstellen von Migrationen muss eine neue App dort mit ihrem korrekten AppConfig-Pfad eingetragen werden. Insbesondere ist `wallet` im aktuellen Stand noch nicht registriert.
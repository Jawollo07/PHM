# Wallet-App

Die Wallet-App ist für das finanzielle Guthaben eines persönlichen Kundenkontos vorgesehen. Eine Wallet gehört über eine One-to-One-Beziehung zu genau einem `Customer`; sie wird niemals direkt an `User` gebunden.

## Währungs- und Betragsmodell

- Unterstützte Währung: EUR.
- Alle Beträge werden als ganzzahlige Euro-Cent (`*_cents`) gespeichert.
- Der Kontostand darf nicht negativ werden.
- Aktive Holds reduzieren das verfügbare Guthaben, nicht den gebuchten Kontostand.
- Vorgemerkte bzw. noch nicht bestätigte Aufladungen dürfen nicht als verfügbares Guthaben behandelt werden.

## Modelle

| Modell | Aufgabe |
|---|---|
| `Wallet` | Kontostand und Kundenbeziehung |
| `LedgerSigningKey` | Öffentliche Ed25519-Schlüssel und Schlüsselstatus |
| `WalletTransaction` | Unveränderlicher Buchungseintrag mit Sequenznummer, Idempotency-Key, Hash-Verkettung und Signatur |
| `WalletHold` | Temporäre Reservierung von Guthaben |
| `LedgerCheckpoint` | Signierter globaler Prüfpunkt über den Ledger-Zustand |

Buchungstypen sind derzeit `topup`, `purchase`, `refund` und `admin_adjustment`. Gutschriften sind positiv, Käufe negativ.

## Sicherheitsanforderungen

- Private Signaturschlüssel dürfen niemals in dieser Datenbank gespeichert werden. Sie gehören in einen Secret Manager, KMS/HSM oder einen separaten Signaturdienst.
- Buchungen und Checkpoints sind append-only. Die vorhandenen ORM-Schutzmechanismen verhindern normale `save`-/`delete`- und bestimmte QuerySet-Änderungen, ersetzen aber keine Datenbankrechte oder Trigger gegen Raw SQL.
- Jede Buchung muss in einer Datenbanktransaktion erfolgen und gegen parallele Änderungen abgesichert werden.
- Idempotency-Keys müssen Wiederholungen derselben Zahlungs-/Buchungsanfrage sicher erkennen.
- Hashes und Signaturen benötigen ein fest definiertes, versioniertes kanonisches Payload-Format.
- Externe, unabhängig gespeicherte Checkpoints sind nötig, um auch eine vollständige Manipulation oder Kürzung der Datenbank-Historie erkennen zu können.

## Implementierungsstatus

Der aktuelle Stand enthält ausschließlich Datenmodelle. Es gibt noch keine produktive Service-Schicht für Aufladung, Kauf, Rückerstattung, Hold-Erstellung/-Freigabe, Signaturprüfung oder Checkpoint-Erstellung. Es gibt außerdem noch keine Wallet-Views, API-Endpunkte oder fachlichen Tests.

Die App ist derzeit noch nicht in `INSTALLED_APPS` in `backend/core/settings.py` eingetragen. Vor dem Erzeugen und Anwenden von Wallet-Migrationen muss dies mit einem korrekten `AppConfig`-Pfad behoben werden.

## Geplante Service-Schnittstelle

Alle späteren Geldbewegungen sollen über klar definierte Services laufen, beispielsweise:

- `credit_wallet(...)` für bestätigte Gutschriften,
- `debit_wallet(...)` für Käufe,
- `refund_wallet(...)` für Rückerstattungen,
- `place_hold(...)`, `capture_hold(...)` und `release_hold(...)`,
- `verify_wallet_chain(...)` und `create_ledger_checkpoint(...)`.

Diese Namen beschreiben die geplante fachliche Aufteilung; entsprechende Funktionen sind im aktuellen Repository noch nicht vorhanden.
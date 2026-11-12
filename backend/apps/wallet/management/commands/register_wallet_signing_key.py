import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.wallet.models import LedgerSigningKey
from apps.wallet.signing import public_key_from_environment


class Command(BaseCommand):
    help = "Register the Ed25519 public key derived from the external wallet signing secret."

    def handle(self, *args, **options):
        key_id = getattr(settings, "WALLET_LEDGER_KEY_ID", "")
        label = os.environ.get("WALLET_LEDGER_KEY_LABEL", "PHM wallet ledger")
        if not key_id:
            raise CommandError("WALLET_LEDGER_KEY_ID is required.")

        try:
            public_key, fingerprint = public_key_from_environment()
        except Exception as exc:
            raise CommandError(f"Could not load the external Ed25519 key: {exc}") from exc

        existing = LedgerSigningKey.objects.filter(key_id=key_id).first()
        if existing:
            if bytes(existing.public_key) != public_key:
                raise CommandError(
                    "The configured private key does not match the registered public key."
                )
            if existing.status != LedgerSigningKey.Status.ACTIVE:
                raise CommandError(
                    "This key is not active. Key rotation/reactivation must be performed explicitly."
                )
            self.stdout.write(self.style.SUCCESS(
                f"Ledger signing key {key_id} is already registered and active."
            ))
            return

        if LedgerSigningKey.objects.filter(status=LedgerSigningKey.Status.ACTIVE).exists():
            raise CommandError(
                "An active ledger key already exists. Retire it through an audited key-rotation procedure first."
            )

        LedgerSigningKey.objects.create(
            key_id=key_id,
            label=label,
            public_key=public_key,
            fingerprint=fingerprint,
            status=LedgerSigningKey.Status.ACTIVE,
            activated_at=timezone.now(),
        )
        self.stdout.write(self.style.SUCCESS(
            f"Registered public ledger key {key_id}. The private key remains outside the database."
        ))

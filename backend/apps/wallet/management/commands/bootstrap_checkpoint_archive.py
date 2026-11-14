from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.wallet.checkpoint_archive import bootstrap_checkpoint_archive


class Command(BaseCommand):
    help = (
        "Create a trusted external baseline from the currently verified "
        "database checkpoint."
    )

    def handle(self, *args, **options):
        if not settings.WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE:
            raise CommandError(
                "Set WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE to a protected file "
                "outside the database before bootstrapping."
            )
        try:
            checkpoint = bootstrap_checkpoint_archive()
        except Exception as exc:
            raise CommandError(
                f"Checkpoint archive bootstrap failed ({type(exc).__name__}): {exc}"
            ) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Bootstrapped external checkpoint archive at checkpoint "
            f"#{checkpoint.checkpoint_number} ({checkpoint.checkpoint_hash})."
        ))

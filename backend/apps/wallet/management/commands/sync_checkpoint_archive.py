from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.wallet.checkpoint_archive import sync_checkpoint_archive


class Command(BaseCommand):
    help = (
        "Append a verified committed checkpoint suffix after an interrupted "
        "external archive write."
    )

    def handle(self, *args, **options):
        if not settings.WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE:
            raise CommandError(
                "Set WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE to the protected "
                "external archive before syncing."
            )
        try:
            synced = sync_checkpoint_archive()
        except Exception as exc:
            raise CommandError(
                f"Checkpoint archive sync failed ({type(exc).__name__}): {exc}"
            ) from exc

        self.stdout.write(self.style.SUCCESS(
            f"External checkpoint archive verified; appended {synced} checkpoint(s)."
        ))

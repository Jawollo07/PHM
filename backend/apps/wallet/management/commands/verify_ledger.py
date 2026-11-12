from django.core.management.base import BaseCommand, CommandError

from apps.wallet.checkpoints import verify_ledger_checkpoint
from apps.wallet.models import LedgerCheckpoint, Wallet
from apps.wallet.services import verify_wallet_chain
from apps.wallet.signing import verify_payload


class Command(BaseCommand):
    help = "Verify wallet hash/signature chains and the latest signed ledger checkpoint."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-unanchored",
            action="store_true",
            help="Allow a preliminary check when no signed global checkpoint exists.",
        )

    def handle(self, *args, **options):
        wallet_count = Wallet.objects.count()
        transaction_count = 0

        for wallet in Wallet.objects.order_by("pk").iterator():
            try:
                valid = verify_wallet_chain(wallet.pk, verify_payload)
            except Exception as exc:
                raise CommandError(
                    f"Wallet {wallet.pk}: verification raised "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            if not valid:
                raise CommandError(
                    f"Wallet {wallet.pk}: hash chain, signature, sequence, "
                    "or balance verification failed."
                )
            transaction_count += wallet.transactions.count()

        checkpoint = (
            LedgerCheckpoint.objects.select_related("signing_key")
            .order_by("-checkpoint_number")
            .first()
        )
        if checkpoint is None:
            if not options["allow_unanchored"]:
                raise CommandError(
                    "No signed ledger checkpoint exists. Create an initial "
                    "checkpoint before treating this verification as complete. "
                    "Use --allow-unanchored only for a preliminary chain check."
                )
            self.stdout.write(self.style.WARNING(
                "WARNING: wallet chains are valid, but no signed global checkpoint exists."
            ))
        else:
            try:
                valid = verify_ledger_checkpoint(
                    checkpoint.pk,
                    verifier=verify_payload,
                    compare_current_state=True,
                )
            except Exception as exc:
                raise CommandError(
                    f"Checkpoint #{checkpoint.checkpoint_number}: verification raised "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            if not valid:
                raise CommandError(
                    f"Checkpoint #{checkpoint.checkpoint_number}: signature, "
                    "checkpoint chain, or current ledger snapshot verification failed."
                )

        suffix = (
            f", checkpoint #{checkpoint.checkpoint_number}"
            if checkpoint else ", without a signed checkpoint"
        )
        self.stdout.write(self.style.SUCCESS(
            f"Ledger integrity verified: {wallet_count} wallets, "
            f"{transaction_count} transactions{suffix}."
        ))

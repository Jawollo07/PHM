from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from apps.wallet.checkpoints import create_ledger_checkpoint, verify_ledger_checkpoint
from apps.wallet.models import LedgerCheckpoint, LedgerSigningKey, Wallet
from apps.wallet.services import verify_wallet_chain
from apps.wallet.signing import verify_payload


class Command(BaseCommand):
    help = (
        "Verify the current ledger state and append a new signed global checkpoint. "
        "Never creates a checkpoint over an invalid or changed ledger."
    )

    def handle(self, *args, **options):
        wallets = Wallet.objects.order_by("pk")
        for wallet in wallets.iterator():
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
                    "or balance verification failed; no checkpoint was created."
                )

        previous = (
            LedgerCheckpoint.objects.select_related("signing_key")
            .order_by("-checkpoint_number")
            .first()
        )
        if previous is not None:
            try:
                valid = verify_ledger_checkpoint(
                    previous.pk,
                    verifier=verify_payload,
                    compare_current_state=True,
                )
            except Exception as exc:
                raise CommandError(
                    f"Existing checkpoint #{previous.checkpoint_number} could not "
                    f"be verified ({type(exc).__name__}: {exc}); no new checkpoint was created."
                ) from exc
            if not valid:
                raise CommandError(
                    f"Existing checkpoint #{previous.checkpoint_number} does not match "
                    "the current ledger; no new checkpoint was created."
                )

        key_id = getattr(settings, "WALLET_LEDGER_KEY_ID", "")
        signer_path = getattr(settings, "WALLET_LEDGER_SIGNER", "")
        if not key_id or not signer_path:
            raise CommandError(
                "WALLET_LEDGER_KEY_ID and WALLET_LEDGER_SIGNER must be configured."
            )
        try:
            signing_key = LedgerSigningKey.objects.get(
                key_id=key_id,
                status=LedgerSigningKey.Status.ACTIVE,
            )
            signer = import_string(signer_path)
            checkpoint = create_ledger_checkpoint(
                signing_key_id=signing_key.pk,
                signer=signer,
            )
        except LedgerSigningKey.DoesNotExist as exc:
            raise CommandError(
                "The configured WALLET_LEDGER_KEY_ID is not an active registered key."
            ) from exc
        except LedgerSigningKey.MultipleObjectsReturned as exc:
            raise CommandError("The configured ledger signing key is ambiguous.") from exc
        except ImproperlyConfigured as exc:
            raise CommandError(f"Ledger signing configuration error: {exc}") from exc
        except Exception as exc:
            raise CommandError(
                f"Checkpoint creation failed ({type(exc).__name__}): {exc}"
            ) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Created signed ledger checkpoint #{checkpoint.checkpoint_number}: "
            f"{checkpoint.checkpoint_hash} "
            f"({checkpoint.wallet_count} wallets, {checkpoint.transaction_count} transactions)."
        ))

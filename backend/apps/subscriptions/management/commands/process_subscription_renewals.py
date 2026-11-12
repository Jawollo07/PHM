from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.module_loading import import_string

from apps.wallet.models import LedgerSigningKey
from apps.subscriptions.models import Subscription
from apps.subscriptions.services import expire_subscription, renew_subscription


class Command(BaseCommand):
    help = "Process due subscription renewals using customer wallet balances."

    def handle(self, *args, **options):
        now = timezone.now()
        due = Subscription.objects.filter(
            status__in=(Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE),
            next_billing_at__lte=now,
        ).order_by("next_billing_at", "pk")

        if not due.exists():
            self.stdout.write(self.style.SUCCESS("No subscriptions are due."))
            return

        needs_signing = due.filter(
            auto_renew=True,
            cancel_at_period_end=False,
            price_cents__gt=0,
        ).exists()
        signing_key_id = None
        signer = None
        if needs_signing:
            configured_key_id = getattr(settings, "WALLET_LEDGER_KEY_ID", "")
            signer_path = getattr(settings, "WALLET_LEDGER_SIGNER", "")
            if not configured_key_id or not signer_path:
                raise CommandError(
                    "WALLET_LEDGER_KEY_ID and WALLET_LEDGER_SIGNER are required "
                    "for paid automatic renewals."
                )
            try:
                key = LedgerSigningKey.objects.get(
                    key_id=configured_key_id,
                    status=LedgerSigningKey.Status.ACTIVE,
                )
                signer = import_string(signer_path)
                signing_key_id = key.pk
            except LedgerSigningKey.DoesNotExist as exc:
                raise CommandError(
                    "The configured ledger signing key is not registered and active."
                ) from exc
            except (ImportError, AttributeError) as exc:
                raise CommandError("The configured ledger signer could not be loaded.") from exc

        renewed = 0
        past_due = 0
        ended = 0
        for subscription in due.iterator():
            if subscription.cancel_at_period_end or not subscription.auto_renew:
                expire_subscription(subscription.pk, now=now)
                ended += 1
                continue

            entry = renew_subscription(
                subscription.pk,
                signing_key_id=signing_key_id,
                signer=signer,
                now=now,
            )
            if entry is None and subscription.price_cents > 0:
                past_due += 1
            else:
                renewed += 1

        self.stdout.write(self.style.SUCCESS(
            f"Subscription processing complete: {renewed} renewed, "
            f"{past_due} past due, {ended} ended."
        ))

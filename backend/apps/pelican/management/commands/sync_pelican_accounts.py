from django.core.management.base import BaseCommand

from apps.pelican.models import PelicanAccount
from apps.pelican.services import sync_pelican_account


class Command(BaseCommand):
    help = "Create or link Pelican users for verified PHM customers."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--retry-failed", action="store_true")

    def handle(self, *args, **options):
        if options["limit"] < 1 or options["limit"] > 1000:
            self.stderr.write(self.style.ERROR("--limit must be between 1 and 1000"))
            return
        statuses = [PelicanAccount.Status.PENDING]
        if options["retry_failed"]:
            statuses.append(PelicanAccount.Status.FAILED)
        ids = list(PelicanAccount.objects.filter(
            customer__user__email_verified=True, status__in=statuses
        ).order_by("created_at").values_list("pk", flat=True)[:options["limit"]])
        linked = failed = 0
        for account_id in ids:
            account = sync_pelican_account(account_id)
            if account.status == PelicanAccount.Status.LINKED:
                linked += 1
            else:
                failed += 1
        self.stdout.write(self.style.SUCCESS(
            f"Pelican sync finished: {linked} linked, {failed} failed, {len(ids)} processed."
        ))

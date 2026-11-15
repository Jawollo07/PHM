from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.pelican.models import PelicanServer
from apps.pelican.services import sync_pelican_server_access


class Command(BaseCommand):
    help = "Reconcile Pelican server suspension with PHM subscription and order state."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1 or limit > 1000:
            self.stderr.write(self.style.ERROR("--limit must be between 1 and 1000"))
            return

        now = timezone.now()
        records = list(PelicanServer.objects.filter(
            status=PelicanServer.Status.INSTALLED,
            panel_server_id__isnull=False,
        ).filter(
            Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)
        ).order_by("last_attempt_at", "created_at")[:limit])

        suspended = active = failed = 0
        for record in records:
            result, should_suspend = sync_pelican_server_access(record.pk)
            if result.last_error_code:
                failed += 1
            elif should_suspend:
                suspended += 1
            else:
                active += 1

        self.stdout.write(self.style.SUCCESS(
            f"Pelican access sync: {active} active, {suspended} suspended, "
            f"{failed} failed, {len(records)} processed."
        ))

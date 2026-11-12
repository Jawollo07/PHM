from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.orders.models import Order
from apps.pelican.models import PelicanServer
from apps.pelican.services import enqueue_order_provisioning, sync_pelican_server


class Command(BaseCommand):
    help = "Provision and reconcile paid PHM order items in Pelican."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--retry-failed", action="store_true")

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1 or limit > 1000:
            self.stderr.write(self.style.ERROR("--limit must be between 1 and 1000"))
            return

        # Backfill durable jobs for already-paid orders as well as newly paid ones.
        order_ids = list(
            Order.objects.filter(status__in=[
                Order.Status.PAID, Order.Status.PROVISIONING, Order.Status.ACTIVE
            ]).order_by("created_at").values_list("pk", flat=True)[:limit]
        )
        for order_id in order_ids:
            enqueue_order_provisioning(order_id)

        statuses = [PelicanServer.Status.PENDING, PelicanServer.Status.PROVISIONING,
                    PelicanServer.Status.INSTALLING]
        queue = PelicanServer.objects.filter(status__in=statuses)
        if options["retry_failed"]:
            queue = queue | PelicanServer.objects.filter(
                status=PelicanServer.Status.FAILED,
                next_retry_at__lte=timezone.now(),
            )
        ids = list(
            queue.order_by("created_at").values_list("pk", flat=True).distinct()[:limit]
        )
        installed = failed = pending = 0
        for record_id in ids:
            record = sync_pelican_server(record_id)
            if record.status == PelicanServer.Status.INSTALLED:
                installed += 1
            elif record.status == PelicanServer.Status.FAILED:
                failed += 1
            else:
                pending += 1
        self.stdout.write(self.style.SUCCESS(
            f"Pelican provisioning: {installed} installed, {pending} pending/installing, "
            f"{failed} failed, {len(ids)} processed."
        ))

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.auth.models import EmailNotification
from apps.customers.models import CustomerSettings

logger = logging.getLogger(__name__)
STALE_LOCK_AFTER = timedelta(minutes=15)
MAX_BACKOFF_SECONDS = 6 * 60 * 60


def _claim(notification_id, now):
    """Claim a row atomically; conditional UPDATE also protects SQLite workers."""
    with transaction.atomic():
        updated = EmailNotification.objects.filter(
            pk=notification_id,
            status=EmailNotification.Status.PENDING,
            available_at__lte=now,
            attempts__lt=F("max_attempts"),
        ).update(
            status=EmailNotification.Status.PROCESSING,
            locked_at=now,
            attempts=F("attempts") + 1,
        )
    return updated == 1


def _still_allowed(notification):
    if notification.user_id is None:
        return False
    preferences = CustomerSettings.objects.filter(
        customer__user_id=notification.user_id
    ).first()
    if preferences is None:
        return True
    preference_field = {
        EmailNotification.Category.PAYMENT: "payment_notifications",
        EmailNotification.Category.SERVICE: "service_notifications",
        EmailNotification.Category.SECURITY: "security_notifications",
    }[notification.category]
    return preferences.email_notifications and getattr(preferences, preference_field)


class Command(BaseCommand):
    help = "Deliver queued customer emails and retry transient failures with backoff."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1:
            self.stderr.write(self.style.ERROR("--limit must be at least 1."))
            return

        now = timezone.now()
        EmailNotification.objects.filter(
            status=EmailNotification.Status.PROCESSING,
            locked_at__lt=now - STALE_LOCK_AFTER,
        ).update(
            status=EmailNotification.Status.PENDING,
            locked_at=None,
            available_at=now,
            last_error="Recovered stale delivery lock.",
        )

        processed = sent = retried = failed = 0
        candidate_ids = list(
            EmailNotification.objects.filter(
                status=EmailNotification.Status.PENDING,
                available_at__lte=now,
                attempts__lt=F("max_attempts"),
            )
            .order_by("available_at", "created_at")
            .values_list("pk", flat=True)[:limit]
        )

        for notification_id in candidate_ids:
            if not _claim(notification_id, timezone.now()):
                continue
            notification = EmailNotification.objects.get(pk=notification_id)
            processed += 1

            if not _still_allowed(notification):
                notification.status = EmailNotification.Status.FAILED
                notification.last_error = "Recipient unavailable or notifications disabled."
                notification.locked_at = None
                notification.save(update_fields=["status", "last_error", "locked_at"])
                failed += 1
                continue

            try:
                send_mail(
                    notification.subject,
                    notification.message,
                    settings.DEFAULT_FROM_EMAIL,
                    [notification.recipient],
                    fail_silently=False,
                )
            except Exception as exc:
                notification.last_error = f"{type(exc).__name__}: {exc}"[:500]
                notification.locked_at = None
                if notification.attempts >= notification.max_attempts:
                    notification.status = EmailNotification.Status.FAILED
                    failed += 1
                else:
                    delay = min(
                        60 * (2 ** (notification.attempts - 1)),
                        MAX_BACKOFF_SECONDS,
                    )
                    notification.status = EmailNotification.Status.PENDING
                    notification.available_at = timezone.now() + timedelta(seconds=delay)
                    retried += 1
                notification.save(update_fields=[
                    "status", "last_error", "locked_at", "available_at"
                ])
                logger.warning(
                    "Email notification %s failed on attempt %s (%s)",
                    notification.pk, notification.attempts, type(exc).__name__,
                )
                continue

            notification.status = EmailNotification.Status.SENT
            notification.sent_at = timezone.now()
            notification.locked_at = None
            notification.last_error = ""
            notification.save(update_fields=["status", "sent_at", "locked_at", "last_error"])
            sent += 1

        self.stdout.write(self.style.SUCCESS(
            f"Email queue: {processed} processed, {sent} sent, "
            f"{retried} scheduled for retry, {failed} failed."
        ))

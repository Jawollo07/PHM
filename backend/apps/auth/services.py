import hashlib
import logging
import secrets
import smtplib
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import CustomerSettings

from .models import EmailVerification


VERIFICATION_LIFETIME = timedelta(hours=24)
logger = logging.getLogger(__name__)


def issue_email_verification(user, *, request, purpose=EmailVerification.Purpose.REGISTRATION):
    """Create a one-time email verification token; persist only its SHA-256 hash."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    verification = EmailVerification.objects.create(
        user=user,
        email=user.email,
        token_hash=token_hash,
        purpose=purpose,
        expires_at=timezone.now() + VERIFICATION_LIFETIME,
    )
    verification_url = request.build_absolute_uri(
        reverse("verify_email", kwargs={"token": raw_token})
    )
    subject = "PHM – E-Mail-Adresse bestätigen"
    message = (
        f"Hallo {user.username},\n\n"
        "bitte bestätige deine E-Mail-Adresse über diesen Link:\n"
        f"{verification_url}\n\n"
        "Der Link ist 24 Stunden gültig. Wenn du kein Konto angelegt hast, "
        "kannst du diese Nachricht ignorieren."
    )
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    return verification


_NOTIFICATION_PREFERENCES = {
    "payment": "payment_notifications",
    "service": "service_notifications",
    "security": "security_notifications",
}


def _format_eur(cents):
    return f"{cents // 100},{cents % 100:02d} EUR"


def _deliver_notification(user_id, category, subject, message):
    user = get_user_model().objects.filter(pk=user_id).only("email").first()
    if user is None or not user.email:
        return

    preferences = CustomerSettings.objects.filter(customer__user_id=user_id).first()
    if preferences and (
        not preferences.email_notifications
        or not getattr(preferences, _NOTIFICATION_PREFERENCES[category])
    ):
        return

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except (smtplib.SMTPException, OSError) as exc:
        logger.error(
            "Email notification delivery failed (user_id=%s, category=%s, error=%s)",
            user_id,
            category,
            type(exc).__name__,
        )


def _schedule_notification(user_id, category, subject, message):
    transaction.on_commit(
        lambda: _deliver_notification(user_id, category, subject, message),
        robust=True,
    )


def notify_wallet_payment_failed(user_id):
    _schedule_notification(
        user_id,
        "payment",
        "PHM – Zahlung fehlgeschlagen",
        (
            "Die Zahlung für deine Bestellung konnte nicht abgeschlossen werden. "
            "Bitte prüfe dein verfügbares Guthaben und versuche es erneut."
        ),
    )


def notify_order_payment_failed(order_id):
    from apps.orders.models import Order

    def send():
        order = (
            Order.objects.select_related("customer__user")
            .filter(pk=order_id)
            .first()
        )
        if order is None:
            return
        _deliver_notification(
            order.customer.user_id,
            "payment",
            "PHM – Zahlung fehlgeschlagen",
            (
                f"Die Zahlung für Bestellung {order.pk} konnte nicht abgeschlossen werden. "
                "Bitte wende dich an den Support."
            ),
        )

    transaction.on_commit(send, robust=True)


def notify_order_confirmation(order_id):
    from apps.orders.models import Order

    def send():
        order = (
            Order.objects.select_related("customer__user")
            .prefetch_related("items")
            .filter(pk=order_id)
            .first()
        )
        if order is None:
            return

        lines = [
            f"Hallo {order.customer.user.get_username()},",
            "",
            f"deine Bestellung {order.pk} wurde bezahlt.",
            f"Zahlungsdatum: {timezone.localtime(order.paid_at):%d.%m.%Y %H:%M}",
            "",
            "Bestellübersicht:",
        ]
        lines.extend(
            f"- {item.product_name} – {item.plan_name} × {item.quantity}: "
            f"{_format_eur(item.line_total_cents)}"
            for item in order.items.all()
        )
        lines.extend([
            "",
            f"Gesamtbetrag: {_format_eur(order.total_cents)}",
            "",
            "Diese E-Mail ist eine Bestell- und Zahlungsübersicht, keine formale Rechnung.",
        ])
        _deliver_notification(
            order.customer.user_id,
            "payment",
            f"PHM – Bestellbestätigung {str(order.pk)[:8]}",
            "\n".join(lines),
        )

    transaction.on_commit(send, robust=True)


def notify_subscription_payment_failed(subscription_id):
    from apps.subscriptions.models import Subscription

    def send():
        subscription = (
            Subscription.objects.select_related("customer__user", "order_item")
            .filter(pk=subscription_id)
            .first()
        )
        if subscription is None:
            return
        _deliver_notification(
            subscription.customer.user_id,
            "payment",
            "PHM – Abozahlung fehlgeschlagen",
            (
                f"Die Verlängerung von {subscription.order_item.product_name} – "
                f"{subscription.order_item.plan_name} konnte nicht bezahlt werden. "
                "Dein Abonnement ist derzeit überfällig. Bitte lade dein Guthaben auf."
            ),
        )

    transaction.on_commit(send, robust=True)


def notify_subscription_renewed(subscription_id):
    from apps.subscriptions.models import Subscription

    def send():
        subscription = (
            Subscription.objects.select_related("customer__user", "order_item")
            .filter(pk=subscription_id)
            .first()
        )
        if subscription is None:
            return
        period_end = timezone.localtime(subscription.current_period_end)
        _deliver_notification(
            subscription.customer.user_id,
            "payment",
            "PHM – Aboverlängerung und Zahlungsübersicht",
            (
                f"Dein Abonnement {subscription.order_item.product_name} – "
                f"{subscription.order_item.plan_name} wurde verlängert.\n"
                f"Betrag: {_format_eur(subscription.price_cents)}\n"
                f"Bezahlt am: {timezone.localtime(subscription.last_renewed_at):%d.%m.%Y %H:%M}\n"
                f"Abgedeckt bis: {period_end:%d.%m.%Y}\n\n"
                "Diese E-Mail ist eine Zahlungsübersicht, keine formale Rechnung."
            ),
        )

    transaction.on_commit(send, robust=True)


def notify_subscription_expired(subscription_id):
    from apps.subscriptions.models import Subscription

    def send():
        subscription = (
            Subscription.objects.select_related("customer__user", "order_item")
            .filter(pk=subscription_id)
            .first()
        )
        if subscription is None:
            return
        _deliver_notification(
            subscription.customer.user_id,
            "service",
            "PHM – Abonnement beendet",
            (
                f"Dein Abonnement {subscription.order_item.product_name} – "
                f"{subscription.order_item.plan_name} ist beendet."
            ),
        )

    transaction.on_commit(send, robust=True)


def notify_password_changed(user_id):
    _schedule_notification(
        user_id,
        "security",
        "PHM – Passwort geändert",
        (
            "Das Passwort für dein PHM-Konto wurde geändert. "
            "Falls du diese Änderung nicht vorgenommen hast, wende dich bitte umgehend an den Support."
        ),
    )

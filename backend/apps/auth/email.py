import logging

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import render


logger = logging.getLogger(__name__)


def test_mail(request=None):
    """Send a small smoke-test email using the configured app sender."""
    recipient = getattr(settings, "TEST_EMAIL_RECIPIENT", None)
    if request is not None and getattr(request, "user", None) is not None:
        user_email = getattr(request.user, "email", None)
        if user_email:
            recipient = user_email
    if not recipient:
        recipient = (
            getattr(settings, "DEFAULT_FROM_EMAIL", None)
            or getattr(settings, "EMAIL_HOST_USER", None)
        )

    try:
        send_mail(
            subject="PHM test email",
            message="This is a test email from PHM.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
        return render(
            request,
            "auth/test_email.html",
            {"success": True, "message": "Die Test-E-Mail wurde erfolgreich versendet."},
        )
    except Exception:  # pragma: no cover - smoke-test endpoint only
        logger.exception("Could not send test email")
        return render(
            request,
            "auth/test_email.html",
            {"success": False, "message": "Die Test-E-Mail konnte nicht versendet werden."},
            status=500,
        )

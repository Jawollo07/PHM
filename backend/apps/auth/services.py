import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from .models import EmailVerification


VERIFICATION_LIFETIME = timedelta(hours=24)


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

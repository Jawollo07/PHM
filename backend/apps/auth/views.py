import hashlib
import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.customers.models import Customer

from .forms import RegistrationForm
from .models import EmailVerification
from .services import issue_email_verification

logger = logging.getLogger(__name__)


def auth_view(request):
    if request.user.is_authenticated:
        return redirect("account")
    return render(request, "index.html")


def register(request):
    if request.user.is_authenticated:
        return redirect("account")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
                issue_email_verification(
                    user,
                    request=request,
                    purpose=EmailVerification.Purpose.REGISTRATION,
                )
        except IntegrityError:
            form.add_error(None, "Benutzername oder E-Mail-Adresse ist bereits vergeben.")
        else:
            return render(request, "auth/registration_sent.html", {"email": user.email})
    return render(request, "auth/register.html", {"form": form})


def verify_email(request, token):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    verification = (
        EmailVerification.objects.select_related("user")
        .filter(token_hash=token_hash)
        .first()
    )
    if verification is None:
        return render(
            request,
            "auth/verification_result.html",
            {"success": False, "message": "Dieser Bestätigungslink ist ungültig oder wurde bereits verwendet."},
            status=400,
        )

    with transaction.atomic():
        verification = (
            EmailVerification.objects.select_for_update()
            .select_related("user")
            .get(pk=verification.pk)
        )
        if verification.verified_at is not None or verification.expires_at <= timezone.now():
            success = False
            message = "Dieser Bestätigungslink ist abgelaufen oder wurde bereits verwendet."
        elif verification.user.email.lower() != verification.email.lower():
            success = False
            message = "Die E-Mail-Adresse hat sich inzwischen geändert. Bitte fordere eine neue Bestätigung an."
        else:
            user = verification.user
            user.email_verified = True
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified", "email_verified_at", "updated_at"])
            verification.verified_at = timezone.now()
            verification.save(update_fields=["verified_at"])
            success = True
            message = "Deine E-Mail-Adresse wurde bestätigt. Du kannst dich jetzt anmelden."

    return render(
        request,
        "auth/verification_result.html",
        {"success": success, "message": message},
        status=200 if success else 400,
    )


def login(request):
    if request.user.is_authenticated:
        return redirect("account")
    if request.method == "GET":
        return render(request, "index.html")
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    user = authenticate(request, username=username, password=password)
    if user is not None:
        try:
            customer = user.customer
        except Customer.DoesNotExist:
            customer = None
        if customer is not None and not customer.is_active:
            user = None
        elif not user.email_verified:
            user = None
            error = "Bitte bestätige zuerst deine E-Mail-Adresse."
        else:
            error = None
    else:
        error = None

    logger.info("Login attempt for username=%s successful=%s", username, user is not None)
    if user is None:
        return render(
            request,
            "index.html",
            {"error": error or "Ungültiger Benutzername oder Passwort."},
            status=400,
        )
    auth_login(request, user)
    return redirect("account")


def log_out(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    logout(request)
    return redirect("auth")


@login_required(login_url="auth")
def site(request):
    return redirect("account")

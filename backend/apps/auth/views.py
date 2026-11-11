import logging

from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render

logger = logging.getLogger(__name__)


def auth_view(request):
    if request.user.is_authenticated:
        return redirect("account")
    return render(request, "index.html")


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

    # Never log passwords, tokens, or other authentication secrets.
    logger.info("Login attempt for username=%s successful=%s", username, user is not None)

    if user is None:
        return render(
            request,
            "index.html",
            {"error": "Ungültiger Benutzername oder Passwort."},
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

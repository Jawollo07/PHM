from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from apps.auth.forms import VerifiedPasswordResetForm
from apps.auth.views import auth_view, login, log_out, register, site, verify_email
from apps.customers.views import account_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("auth/", auth_view, name="auth"),
    path("auth/login/", login, name="login"),
    path("auth/logout/", log_out, name="logout"),
    path("auth/register/", register, name="register"),
    path("auth/verify/<str:token>/", verify_email, name="verify_email"),
    path(
        "auth/password-reset/",
        auth_views.PasswordResetView.as_view(
            form_class=VerifiedPasswordResetForm,
            template_name="auth/password_reset_form.html",
            email_template_name="auth/password_reset_email.html",
            subject_template_name="auth/password_reset_subject.txt",
            success_url="/auth/password-reset/done/",
        ),
        name="password_reset",
    ),
    path(
        "auth/password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="auth/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "auth/password-reset/confirm/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="auth/password_reset_confirm.html",
            success_url="/auth/password-reset/complete/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "auth/password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="auth/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("auth/login/test/", site, name="login_test"),
    path("account/", account_view, name="account"),
]

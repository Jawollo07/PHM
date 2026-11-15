from io import StringIO
import smtplib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.auth.cli import main as run_auth_cli
from apps.wallet.models import Wallet

User = get_user_model()


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='correct-password',
            email_verified=True,
        )

    def test_login_with_valid_credentials_creates_session(self):
        response = self.client.post(
            '/auth/login/',
            {'username': 'testuser', 'password': 'correct-password'},
        )

        self.assertRedirects(response, '/account/')
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        self.assertTrue(hasattr(self.user, 'customer'))
        self.assertTrue(Wallet.objects.filter(customer=self.user.customer).exists())

    def test_suspended_customer_cannot_log_in(self):
        self.user.customer.status = 'suspended'
        self.user.customer.save(update_fields=['status', 'updated_at'])
        response = self.client.post(
            '/auth/login/',
            {'username': 'testuser', 'password': 'correct-password'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_with_invalid_credentials_shows_error(self):
        response = self.client.post(
            '/auth/login/',
            {'username': 'testuser', 'password': 'wrong-password'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Ungültiger Benutzername oder Passwort.', status_code=400)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_email_is_not_used_as_login_name(self):
        response = self.client.post(
            '/auth/login/',
            {'username': 'test@example.com', 'password': 'correct-password'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logout_requires_post(self):
        response = self.client.get('/auth/logout/')
        self.assertEqual(response.status_code, 405)

    def test_logout_post_clears_session(self):
        self.client.force_login(self.user)
        response = self.client.post('/auth/logout/')
        self.assertRedirects(response, '/auth/')
        self.assertNotIn('_auth_user_id', self.client.session)

    @patch("apps.auth.password_forms.sync_pelican_password")
    def test_password_change_sends_security_notification(self, _sync_password):
        from django.core import mail
        from django.urls import reverse

        self.client.force_login(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("password_change"), {
                "old_password": "correct-password",
                "new_password1": "New-Strong-Passphrase-2026!",
                "new_password2": "New-Strong-Passphrase-2026!",
            })

        self.assertRedirects(response, reverse("password_change_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Passwort geändert", mail.outbox[0].subject)

    def test_success_page_requires_authentication(self):
        response = self.client.get('/auth/login/test/')

        self.assertRedirects(response, '/auth/?next=/auth/login/test/')


class SuperuserManagerTests(TestCase):
    def test_create_superuser_sets_required_permissions(self):
        user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='secure-test-password',
        )

        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password('secure-test-password'))


class UserCliTests(TestCase):
    @patch('apps.auth.cli.getpass', side_effect=['secure-new-password', 'secure-new-password'])
    def test_create_user_command_creates_user_with_hashed_password(self, _getpass):
        output = StringIO()

        with patch('sys.stdout', output):
            exit_code = run_auth_cli([
                'create-user',
                '--username',
                'cli-user',
                '--email',
                'cli-user@example.com',
            ])

        user = User.objects.get(username='cli-user')
        self.assertEqual(exit_code, 0)
        self.assertTrue(user.check_password('secure-new-password'))
        self.assertIn("Benutzer 'cli-user' wurde erstellt.", output.getvalue())

    @patch('apps.auth.cli.getpass', side_effect=['secure-new-password', 'different-password'])
    def test_create_user_command_rejects_mismatched_passwords(self, _getpass):
        errors = StringIO()

        with patch('sys.stderr', errors):
            exit_code = run_auth_cli([
                'create-user',
                '--username',
                'cli-user',
                '--email',
                'cli-user@example.com',
            ])

        self.assertEqual(exit_code, 2)
        self.assertFalse(User.objects.filter(username='cli-user').exists())
        self.assertIn('stimmen nicht überein', errors.getvalue())


class RegistrationAndEmailVerificationTests(TestCase):
    def setUp(self):
        from django.test import override_settings

        self.email_backend = override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
        )
        self.email_backend.enable()

    def tearDown(self):
        self.email_backend.disable()

    def _login_as_staff(self):
        staff = User.objects.create_user(
            username="mail-admin",
            email="mail-admin@example.com",
            password="secure-test-password",
            is_staff=True,
            email_verified=True,
        )
        self.client.force_login(staff)

    @patch("apps.auth.email.send_mail")
    def test_test_email_endpoint_renders_success_page(self, send_mail_mock):
        from django.urls import reverse

        self._login_as_staff()
        response = self.client.post(reverse("test_mail"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auth/test_email.html")
        self.assertContains(response, "Die Test-E-Mail wurde erfolgreich versendet.")
        send_mail_mock.assert_called_once()

    def test_test_email_endpoint_rejects_get_requests(self):
        from django.urls import reverse

        self._login_as_staff()
        response = self.client.get(reverse("test_mail"))
        self.assertEqual(response.status_code, 405)

    def test_test_email_endpoint_requires_staff(self):
        from django.urls import reverse

        customer = User.objects.create_user(
            username="mail-customer",
            email="mail-customer@example.com",
            password="secure-test-password",
            email_verified=True,
        )
        self.client.force_login(customer)
        response = self.client.post(reverse("test_mail"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/", response.url)

    @patch("apps.auth.email.send_mail", side_effect=OSError("SMTP unavailable"))
    def test_test_email_endpoint_renders_error_page(self, _send_mail_mock):
        from django.urls import reverse

        self._login_as_staff()
        response = self.client.post(reverse("test_mail"))

        self.assertEqual(response.status_code, 500)
        self.assertTemplateUsed(response, "auth/test_email.html")
        self.assertContains(
            response,
            "Die Test-E-Mail konnte nicht versendet werden.",
            status_code=500,
        )

    def test_registration_creates_personal_customer_wallet_and_hashed_token(self):
        import hashlib
        import re

        from django.conf import settings
        from django.core import mail
        from django.urls import reverse
        from apps.auth.models import EmailVerification

        response = self.client.post(reverse("register"), {
            "username": "new-private-customer",
            "email": "new-private@example.com",
            "password1": "Strong-Passphrase-2026!x",
            "password2": "Strong-Passphrase-2026!x",
        })

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auth/registration_sent.html")
        user = User.objects.get(username="new-private-customer")
        self.assertFalse(user.email_verified)
        self.assertTrue(hasattr(user, "customer"))
        self.assertTrue(Wallet.objects.filter(customer=user.customer).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email, settings.DEFAULT_FROM_EMAIL)

        token = re.search(r"/auth/verify/([^/]+)", mail.outbox[0].body).group(1)
        verification = EmailVerification.objects.get(user=user)
        self.assertEqual(
            verification.token_hash,
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(verification.token_hash, token)

    @patch(
        "apps.auth.services.send_mail",
        side_effect=smtplib.SMTPRecipientsRefused(
            {"invalid@example.com": (550, b"5.1.2 Mailbox does not exist")}
        ),
    )
    def test_registration_shows_recipient_error_and_rolls_back(self, _send_mail_mock):
        from django.urls import reverse
        from apps.auth.models import EmailVerification

        response = self.client.post(reverse("register"), {
            "username": "failed-delivery",
            "email": "invalid@example.com",
            "password1": "Strong-Passphrase-2026!x",
            "password2": "Strong-Passphrase-2026!x",
        })

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auth/register.html")
        self.assertContains(response, "Diese E-Mail-Adresse wurde vom Mailserver abgelehnt.")
        self.assertFalse(User.objects.filter(username="failed-delivery").exists())
        self.assertFalse(
            EmailVerification.objects.filter(email="invalid@example.com").exists()
        )

    def test_email_verification_enables_login_and_is_one_time(self):
        import re

        from django.core import mail
        from django.urls import reverse

        self.client.post(reverse("register"), {
            "username": "verify-me",
            "email": "verify-me@example.com",
            "password1": "Strong-Passphrase-2026!x",
            "password2": "Strong-Passphrase-2026!x",
        })
        token = re.search(r"/auth/verify/([^/]+)", mail.outbox[0].body).group(1)

        response = self.client.get(reverse("verify_email", kwargs={"token": token}))
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(username="verify-me")
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertIsNotNone(user.email_verified_at)

        second_response = self.client.get(
            reverse("verify_email", kwargs={"token": token})
        )
        self.assertEqual(second_response.status_code, 400)

        login_response = self.client.post(reverse("login"), {
            "username": "verify-me",
            "password": "Strong-Passphrase-2026!x",
        })
        self.assertRedirects(login_response, reverse("account"))

    def test_unverified_user_cannot_log_in(self):
        from django.urls import reverse

        user = User.objects.create_user(
            username="pending-verification",
            email="pending@example.com",
            password="Strong-Passphrase-2026!x",
        )
        response = self.client.post(reverse("login"), {
            "username": user.username,
            "password": "Strong-Passphrase-2026!x",
        })
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "Bitte bestätige zuerst deine E-Mail-Adresse.",
            status_code=400,
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        from django.urls import reverse

        User.objects.create_user(
            username="existing-customer",
            email="already-used@example.com",
            password="Strong-Passphrase-2026!x",
        )
        response = self.client.post(reverse("register"), {
            "username": "different-user",
            "email": "ALREADY-USED@example.com",
            "password1": "Strong-Passphrase-2026!x",
            "password2": "Strong-Passphrase-2026!x",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Diese E-Mail-Adresse wird bereits verwendet.",
        )
        self.assertFalse(User.objects.filter(username="different-user").exists())

    def test_password_reset_sends_link_only_to_verified_accounts(self):
        from django.core import mail
        from django.urls import reverse

        verified = User.objects.create_user(
            username="reset-verified",
            email="reset-verified@example.com",
            password="Old-Strong-Passphrase-2026!",
            email_verified=True,
        )
        User.objects.create_user(
            username="reset-unverified",
            email="reset-unverified@example.com",
            password="Old-Strong-Passphrase-2026!",
            email_verified=False,
        )

        response = self.client.post(reverse("password_reset"), {
            "email": verified.email,
        })
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("password-reset/confirm/", mail.outbox[0].body)

        self.client.post(reverse("password_reset"), {
            "email": "reset-unverified@example.com",
        })
        self.assertEqual(len(mail.outbox), 1)

    def test_password_reset_page_does_not_reveal_unknown_email_addresses(self):
        from django.urls import reverse

        response = self.client.post(reverse("password_reset"), {
            "email": "not-registered@example.com",
        })
        self.assertRedirects(response, reverse("password_reset_done"))
        done = self.client.get(reverse("password_reset_done"))
        self.assertContains(done, "Wenn ein bestätigtes Konto zu dieser Adresse existiert")

    @patch("apps.auth.password_forms.sync_pelican_password")
    def test_password_reset_completion_sends_security_notification(self, _sync_password):
        from django.contrib.auth.tokens import default_token_generator
        from django.core import mail
        from django.urls import reverse
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        user = User.objects.create_user(
            username="reset-notification",
            email="reset-notification@example.com",
            password="Old-Strong-Passphrase-2026!",
            email_verified=True,
        )
        confirm_url = reverse(
            "password_reset_confirm",
            kwargs={
                "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
                "token": default_token_generator.make_token(user),
            },
        )
        confirm_response = self.client.get(confirm_url)
        self.assertEqual(confirm_response.status_code, 302)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(confirm_response["Location"], {
                "new_password1": "New-Strong-Passphrase-2026!",
                "new_password2": "New-Strong-Passphrase-2026!",
            })

        self.assertRedirects(response, reverse("password_reset_complete"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Passwort geändert", mail.outbox[0].subject)

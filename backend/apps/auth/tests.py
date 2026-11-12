from io import StringIO
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

    def test_registration_creates_personal_customer_wallet_and_hashed_token(self):
        import hashlib
        import re

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

        token = re.search(r"/auth/verify/([^/]+)", mail.outbox[0].body).group(1)
        verification = EmailVerification.objects.get(user=user)
        self.assertEqual(
            verification.token_hash,
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(verification.token_hash, token)

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

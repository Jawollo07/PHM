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
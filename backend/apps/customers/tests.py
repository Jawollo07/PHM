from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.auth.models import UserProfile
from apps.customers.models import Customer, CustomerAddress, CustomerSettings
from apps.wallet.models import Wallet


class AccountViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='testuser',
            email='test@example.com',
            password='secure-test-password',
        )
        self.client.force_login(self.user)

    def test_user_creation_provisions_customer_settings_and_wallet(self):
        customer = Customer.objects.get(user=self.user)
        self.assertTrue(CustomerSettings.objects.filter(customer=customer).exists())
        self.assertTrue(Wallet.objects.filter(customer=customer).exists())

    def test_suspended_customer_session_is_terminated(self):
        customer = Customer.objects.get(user=self.user)
        customer.status = Customer.Status.SUSPENDED
        customer.save(update_fields=['status', 'updated_at'])

        response = self.client.get('/account/')

        self.assertRedirects(response, '/auth/')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_account_page_displays_provisioned_customer(self):
        response = self.client.get('/account/')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'customers/index.html')
        self.assertContains(response, 'testuser')
        self.assertContains(response, 'test@example.com')
        self.assertContains(response, 'Kontaktdaten')

    def test_account_page_displays_wallet_balances_without_payment_actions(self):
        response = self.client.get('/account/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mein Guthaben')
        self.assertContains(response, 'Kontostand')
        self.assertContains(response, 'Verfügbar')
        self.assertContains(response, '0,00 EUR')
        self.assertContains(response, 'Online-Zahlungsmethoden sind nicht aktiviert')
        self.assertNotContains(response, 'Jetzt bezahlen')

    def test_account_page_displays_customer_phone_number(self):
        customer = Customer.objects.get(user=self.user)
        customer.phone_number = '0123456789'
        customer.save(update_fields=['phone_number', 'updated_at'])

        response = self.client.get('/account/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '0123456789')

    def test_account_page_updates_user_customer_and_settings(self):
        self.user.email_verified = True
        self.user.email_verified_at = timezone.now()
        self.user.save(update_fields=['email_verified', 'email_verified_at'])
        response = self.client.post(
            '/account/',
            {
                'username': 'updated-user',
                'email': 'updated@example.com',
                'phone_number': '0123456789',
                'language': 'en',
                'recipient_name': '',
                'company_name': '',
                'street': '',
                'house_number': '',
                'address_line_2': '',
                'postal_code': '',
                'city': '',
                'state': '',
                'country': '',
                'email_notifications': 'on',
                'marketing_emails': 'on',
            },
        )

        self.assertRedirects(response, '/account/')
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'updated-user')
        self.assertEqual(self.user.email, 'updated@example.com')
        self.assertFalse(self.user.email_verified)
        self.assertIsNone(self.user.email_verified_at)

        customer = Customer.objects.get(user=self.user)
        self.assertEqual(customer.phone_number, '0123456789')
        settings = CustomerSettings.objects.get(customer=customer)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.language, 'en')
        self.assertTrue(settings.email_notifications)
        self.assertFalse(settings.service_notifications)
        self.assertTrue(settings.marketing_emails)

    def test_account_page_creates_address_when_submitted(self):
        response = self.client.post(
            '/account/',
            {
                'username': 'testuser',
                'email': 'test@example.com',
                'phone_number': '',
                'language': 'de',
                'recipient_name': 'Test User',
                'street': 'Musterstraße',
                'house_number': '12',
                'postal_code': '12345',
                'city': 'Berlin',
                'country': 'Germany',
            },
        )

        self.assertRedirects(response, '/account/')
        customer = Customer.objects.get(user=self.user)
        address = CustomerAddress.objects.get(customer=customer)
        self.assertEqual(address.address_type, CustomerAddress.Type.CONTACT)
        self.assertEqual(address.city, 'Berlin')

    def test_account_page_rejects_duplicate_email(self):
        get_user_model().objects.create_user(
            username='another-user',
            email='other@example.com',
            password='secure-test-password',
        )

        response = self.client.post(
            '/account/',
            {
                'username': 'testuser',
                'email': 'other@example.com',
                'phone_number': '',
                'language': 'de',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Diese E-Mail-Adresse wird bereits verwendet.')
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'test@example.com')

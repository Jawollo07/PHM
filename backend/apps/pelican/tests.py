from django.test import SimpleTestCase, TestCase, override_settings

from apps.auth.models import User
from apps.customers.models import Customer
from .client import PelicanAPIError, PelicanClient
from .models import PelicanAccount
from .services import sync_pelican_account


class FakePelicanClient:
    def __init__(self, remote=None, error=None):
        self.remote = remote
        self.error = error
        self.created = []

    def ensure_user(self, *, email, username, first_name):
        self.created.append((email, username, first_name))
        if self.error:
            raise self.error
        return self.remote or {"id": 321, "email": email}, True


class PelicanAccountSyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="private-customer",
            email="private@example.com",
            password="test-password",
        )
        self.user.email_verified = True
        self.user.save(update_fields=["email_verified", "updated_at"])
        self.customer = Customer.objects.get(user=self.user)
        self.account = PelicanAccount.objects.get(customer=self.customer)

    def test_verified_customer_is_linked_to_created_panel_user(self):
        client = FakePelicanClient()
        account = sync_pelican_account(self.account.pk, client=client)
        self.assertEqual(account.status, PelicanAccount.Status.LINKED)
        self.assertEqual(account.panel_user_id, 321)
        self.assertEqual(account.panel_email, self.user.email)
        self.assertEqual(account.attempts, 1)
        self.assertEqual(len(client.created), 1)

    def test_panel_email_mismatch_is_not_linked(self):
        client = FakePelicanClient(remote={"id": 321, "email": "attacker@example.com"})
        account = sync_pelican_account(self.account.pk, client=client)
        self.assertEqual(account.status, PelicanAccount.Status.FAILED)
        self.assertEqual(account.last_error_code, "panel_identity_mismatch")
        self.assertIsNone(account.panel_user_id)

    def test_api_error_is_recorded_without_exposing_details(self):
        client = FakePelicanClient(error=PelicanAPIError("http_503"))
        account = sync_pelican_account(self.account.pk, client=client)
        self.assertEqual(account.status, PelicanAccount.Status.FAILED)
        self.assertEqual(account.last_error_code, "http_503")
        self.assertNotIn("token", account.last_error_code)

    def test_linked_account_is_idempotent(self):
        client = FakePelicanClient()
        sync_pelican_account(self.account.pk, client=client)
        account = sync_pelican_account(self.account.pk, client=client)
        self.assertEqual(account.panel_user_id, 321)
        self.assertEqual(len(client.created), 1)

    def test_unverified_customer_is_not_provisioned(self):
        self.user.email_verified = False
        self.user.save(update_fields=["email_verified", "updated_at"])
        account = sync_pelican_account(self.account.pk, client=FakePelicanClient())
        self.assertEqual(account.status, PelicanAccount.Status.PENDING)


class PelicanClientConfigurationTests(SimpleTestCase):
    @override_settings(PELICAN_PANEL_URL="http://panel.example.com", PELICAN_APPLICATION_API_TOKEN="secret")
    def test_plain_http_is_rejected(self):
        with self.assertRaises(PelicanAPIError) as raised:
            PelicanClient()
        self.assertEqual(raised.exception.code, "https_required")


class PelicanPasswordAPIClientTests(SimpleTestCase):
    @override_settings(PELICAN_PANEL_URL="https://panel.example.com", PELICAN_APPLICATION_API_TOKEN="test-token")
    def test_password_update_reads_required_fields_and_patches_them_with_password(self):
        from unittest.mock import patch

        client = PelicanClient()
        with patch.object(client, "_request", side_effect=[
            {"attributes": {
                "email": "customer@example.com",
                "username": "customer-123",
                "first_name": "Customer",
                "last_name": "PHM",
            }},
            {},
        ]) as request:
            client.update_user_password(123, "New-Strong-Password-2026!")
        self.assertEqual(request.call_args_list[0].args, ("GET", "users/123"))
        method, path = request.call_args_list[1].args[:2]
        payload = request.call_args_list[1].args[2]
        self.assertEqual((method, path), ("PATCH", "users/123"))
        self.assertEqual(payload["password"], "New-Strong-Password-2026!")
        self.assertEqual(payload["email"], "customer@example.com")


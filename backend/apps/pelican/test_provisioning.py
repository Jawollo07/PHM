from django.test import TestCase
from django.utils import timezone

from apps.auth.models import User
from apps.catalog.models import HostingPlan, HostingProduct
from apps.orders.models import Order, OrderItem
from apps.pelican.models import PelicanAccount, PelicanServer
from apps.pelican.services import sync_pelican_server
from apps.customers.models import Customer


class FakeProvisioningClient:
    def __init__(self, remote=None, created=None, detail=None):
        self.remote = remote
        self.created = created
        self.detail = detail
        self.payloads = []

    def find_server_by_external_id(self, external_id):
        return self.remote

    def create_server(self, payload):
        self.payloads.append(payload)
        return self.created

    def get_server(self, panel_server_id):
        return self.detail or self.created or self.remote


class PelicanServerProvisioningTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="provision-customer",
            email="provision@example.com",
            password="not-used-in-test",
            email_verified=True,
        )
        self.customer = Customer.objects.get(user=self.user)
        PelicanAccount.objects.create(
            customer=self.customer,
            panel_user_id=55,
            panel_email=self.user.email,
            status=PelicanAccount.Status.LINKED,
            linked_at=timezone.now(),
        )
        product = HostingProduct.objects.create(
            name="Minecraft", slug="minecraft", is_active=True
        )
        self.plan = HostingPlan.objects.create(
            product=product,
            name="Standard",
            slug="standard",
            price_cents=0,
            is_active=True,
            resource_limits={
                "pelican": {
                    "egg_id": 4,
                    "allocation_id": 91,
                    "docker_image": "ghcr.io/pelican/yolks:java_21",
                    "startup": "java -jar server.jar",
                    "environment": {"SERVER_JARFILE": "server.jar"},
                    "limits": {
                        "memory": 4096, "swap": 0, "disk": 10240, "io": 500, "cpu": 200
                    },
                    "feature_limits": {"databases": 1, "allocations": 1, "backups": 2},
                }
            },
        )
        order = Order.objects.create(
            customer=self.customer,
            status=Order.Status.PAID,
            total_cents=0,
            idempotency_key="test-provisioning-order",
            paid_at=timezone.now(),
        )
        item = OrderItem.objects.create(
            order=order,
            plan=self.plan,
            product_name="Minecraft",
            plan_name="Standard",
            description="",
            quantity=1,
            unit_price_cents=0,
            setup_fee_cents=0,
            line_total_cents=0,
            billing_interval_unit="once",
            billing_interval_count=1,
            resource_limits=self.plan.resource_limits,
        )
        self.record = PelicanServer.objects.create(
            order_item=item,
            customer=self.customer,
            external_id=f"phm-orderitem-{item.pk}",
        )

    def test_paid_order_creates_remote_server_and_enters_installing_state(self):
        external_id = self.record.external_id
        client = FakeProvisioningClient(created={
            "id": 88,
            "user": 55,
            "external_id": external_id,
            "uuid": "remote-uuid",
            "identifier": "abc123",
            "name": "Minecraft Standard",
            "installed_at": None,
        })
        record = sync_pelican_server(self.record.pk, client=client)
        self.assertEqual(record.status, PelicanServer.Status.INSTALLING)
        self.assertEqual(record.panel_server_id, 88)
        self.assertEqual(record.order_item.order.status, Order.Status.PROVISIONING)
        self.assertEqual(len(client.payloads), 1)
        self.assertEqual(client.payloads[0]["user"], 55)
        self.assertEqual(client.payloads[0]["allocation"], {"default": 91})
        self.assertEqual(client.payloads[0]["external_id"], external_id)

    def test_retry_reconciles_existing_external_id_without_creating_duplicate(self):
        external_id = self.record.external_id
        existing = {
            "id": 88, "user": 55, "external_id": external_id, "uuid": "remote-uuid",
            "identifier": "abc123", "name": "Minecraft Standard",
        }
        client = FakeProvisioningClient(
            remote=existing,
            detail={**existing, "installed_at": "2026-11-12T12:00:00Z"},
        )
        record = sync_pelican_server(self.record.pk, client=client)
        self.assertEqual(record.status, PelicanServer.Status.INSTALLED)
        self.assertEqual(record.panel_server_id, 88)
        self.assertEqual(record.order_item.order.status, Order.Status.ACTIVE)
        self.assertEqual(client.payloads, [])

    def test_missing_pelican_plan_configuration_fails_closed(self):
        order = self.record.order_item.order
        item = OrderItem.objects.create(
            order=order,
            plan=self.plan,
            product_name="Minecraft",
            plan_name="Broken",
            description="",
            quantity=1,
            unit_price_cents=0,
            setup_fee_cents=0,
            line_total_cents=0,
            billing_interval_unit="once",
            billing_interval_count=1,
            resource_limits={},
        )
        record_to_test = PelicanServer.objects.create(
            order_item=item,
            customer=self.customer,
            external_id=f"phm-orderitem-{item.pk}",
        )
        client = FakeProvisioningClient()
        record = sync_pelican_server(record_to_test.pk, client=client)
        self.assertEqual(record.status, PelicanServer.Status.FAILED)
        self.assertEqual(record.last_error_code, "pelican_config_missing")
        self.assertEqual(client.payloads, [])

    def test_existing_server_owned_by_another_panel_user_is_rejected(self):
        external_id = self.record.external_id
        existing = {
            "id": 88, "user": 999, "external_id": external_id,
            "uuid": "remote-uuid", "identifier": "abc123",
            "name": "Unexpected owner",
        }
        client = FakeProvisioningClient(
            remote=existing,
            detail=existing,
        )
        record = sync_pelican_server(self.record.pk, client=client)
        self.assertEqual(record.status, PelicanServer.Status.FAILED)
        self.assertEqual(record.last_error_code, "server_owner_mismatch")
        self.assertIsNone(record.panel_server_id)
        self.assertEqual(client.payloads, [])

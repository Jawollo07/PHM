from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.auth.models import User
from apps.catalog.models import HostingPlan, HostingProduct
from apps.customers.models import Customer
from apps.orders.models import Order, OrderItem
from apps.pelican.models import PelicanAccount, PelicanServer
from apps.pelican.services import enqueue_order_provisioning, sync_pelican_server


class FakeProvisioningClient:
    def __init__(self, *, remote=None, installed=False):
        self.remote = remote
        self.installed = installed
        self.payloads = []
        self.next_id = 80

    def find_server_by_external_id(self, external_id):
        if self.remote and self.remote.get("external_id") == external_id:
            return self.remote
        return None

    def create_server(self, payload):
        self.payloads.append(payload)
        self.next_id += 1
        self.remote = {
            "id": self.next_id,
            "user": 55,
            "external_id": payload["external_id"],
            "uuid": f"remote-{self.next_id}",
            "identifier": f"server{self.next_id}",
            "name": payload["name"],
        }
        return self.remote

    def get_server(self, panel_server_id):
        return {
            **(self.remote or {}),
            "installed_at": "2026-11-15T12:00:00Z" if self.installed else None,
        }


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
                        "memory": 4096, "swap": 0, "disk": 10240, "io": 0, "cpu": 200
                    },
                    "feature_limits": {"databases": 1, "allocations": 1, "backups": 2},
                }
            },
        )
        self.order, self.item = self.make_order(quantity=1, key="base-order")
        self.record = enqueue_order_provisioning(self.order.pk)[0]

    def make_order(self, *, quantity, key):
        order = Order.objects.create(
            customer=self.customer,
            status=Order.Status.PAID,
            total_cents=0,
            idempotency_key=key,
            paid_at=timezone.now(),
        )
        item = OrderItem.objects.create(
            order=order,
            plan=self.plan,
            product_name="Minecraft",
            plan_name="Standard",
            description="",
            quantity=quantity,
            unit_price_cents=0,
            setup_fee_cents=0,
            line_total_cents=0,
            billing_interval_unit="once",
            billing_interval_count=1,
            resource_limits=self.plan.resource_limits,
        )
        return order, item

    def test_zero_io_limit_is_accepted_by_pelican(self):
        client = FakeProvisioningClient()
        record = sync_pelican_server(self.record.pk, client=client)
        self.assertEqual(record.status, PelicanServer.Status.INSTALLING)
        self.assertEqual(client.payloads[0]["limits"]["io"], 0)

    def test_quantity_creates_one_durable_record_per_server_unit(self):
        order, item = self.make_order(quantity=3, key="three-server-order")
        records = enqueue_order_provisioning(order.pk)
        self.assertEqual(len(records), 3)
        self.assertEqual(
            list(PelicanServer.objects.filter(order_item=item).order_by("quantity_index")
                 .values_list("quantity_index", flat=True)),
            [1, 2, 3],
        )
        self.assertEqual(len({record.external_id for record in records}), 3)
        self.assertEqual(enqueue_order_provisioning(order.pk), records)

    def test_order_activates_only_after_every_purchased_unit_is_installed(self):
        order, _item = self.make_order(quantity=2, key="two-server-order")
        records = enqueue_order_provisioning(order.pk)
        first = sync_pelican_server(records[0].pk, client=FakeProvisioningClient(installed=True))
        self.assertEqual(first.status, PelicanServer.Status.INSTALLED)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PROVISIONING)

        second = sync_pelican_server(records[1].pk, client=FakeProvisioningClient(installed=True))
        self.assertEqual(second.status, PelicanServer.Status.INSTALLED)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.ACTIVE)

    def test_existing_server_owned_by_another_panel_user_is_rejected(self):
        remote = {
            "id": 88, "user": 999, "external_id": self.record.external_id,
            "uuid": "remote-uuid", "identifier": "abc123", "name": "Unexpected owner",
        }

        class ExistingClient(FakeProvisioningClient):
            def find_server_by_external_id(self, external_id):
                return remote

            def get_server(self, panel_server_id):
                return remote

        record = sync_pelican_server(self.record.pk, client=ExistingClient())
        self.assertEqual(record.status, PelicanServer.Status.FAILED)
        self.assertEqual(record.last_error_code, "server_owner_mismatch")
        self.assertIsNone(record.panel_server_id)

    def test_backfill_does_not_stop_after_first_limit_page(self):
        for index in range(51):
            self.make_order(quantity=1, key=f"backfill-{index}")
        first = PelicanServer.objects.filter(status=PelicanServer.Status.PENDING).first()

        def leave_pending(record_id):
            return PelicanServer.objects.get(pk=record_id)

        with patch("apps.pelican.management.commands.provision_pelican_servers.sync_pelican_server",
                   side_effect=leave_pending):
            call_command("provision_pelican_servers", "--limit", "1")

        self.assertEqual(PelicanServer.objects.count(), 52)

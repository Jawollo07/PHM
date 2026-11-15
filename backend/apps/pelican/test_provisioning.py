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


class PelicanServerProvisioningFixture:
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

class PelicanServerProvisioningTests(PelicanServerProvisioningFixture, TestCase):
    def test_zero_io_limit_is_accepted_by_pelican(self):
        client = FakeProvisioningClient()
        record = sync_pelican_server(self.record.pk, client=client)
        self.assertEqual(record.status, PelicanServer.Status.INSTALLING)
        self.assertEqual(client.payloads[0]["limits"]["io"], 0)

    def test_invalid_catalog_configuration_fails_closed_before_server_creation(self):
        invalid_resources = {
            **self.plan.resource_limits,
            "pelican": {
                **self.plan.resource_limits["pelican"],
                "egg_id": True,
            },
        }
        invalid_plan = HostingPlan.objects.create(
            product=self.plan.product,
            name="Invalid Egg Plan",
            slug="invalid-egg-plan",
            price_cents=0,
            resource_limits=invalid_resources,
        )
        order = Order.objects.create(
            customer=self.customer,
            status=Order.Status.PAID,
            total_cents=0,
            idempotency_key="invalid-egg-order",
            paid_at=timezone.now(),
        )
        item = OrderItem.objects.create(
            order=order,
            plan=invalid_plan,
            product_name="Minecraft",
            plan_name="Invalid Egg Plan",
            description="",
            quantity=1,
            unit_price_cents=0,
            setup_fee_cents=0,
            line_total_cents=0,
            billing_interval_unit="once",
            billing_interval_count=1,
            resource_limits=invalid_resources,
        )
        record = enqueue_order_provisioning(order.pk)[0]
        client = FakeProvisioningClient()

        result = sync_pelican_server(record.pk, client=client)

        self.assertEqual(result.status, PelicanServer.Status.FAILED)
        self.assertEqual(result.last_error_code, "invalid_egg_id")
        self.assertEqual(client.payloads, [])

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
        client = FakeProvisioningClient(installed=True)
        first = sync_pelican_server(records[0].pk, client=client)
        self.assertEqual(first.status, PelicanServer.Status.INSTALLED)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PROVISIONING)

        second = sync_pelican_server(records[1].pk, client=client)
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

    def test_queue_rotation_does_not_process_same_installing_record_forever(self):
        for index in range(2):
            order, _item = self.make_order(quantity=1, key=f"fair-queue-{index}")
            enqueue_order_provisioning(order.pk)
        selected = []

        def mark_attempted(record_id):
            record = PelicanServer.objects.get(pk=record_id)
            selected.append(record.pk)
            record.last_attempt_at = timezone.now()
            record.save(update_fields=["last_attempt_at", "updated_at"])
            return record

        with patch("apps.pelican.management.commands.provision_pelican_servers.sync_pelican_server",
                   side_effect=mark_attempted):
            call_command("provision_pelican_servers", "--limit", "1")
            call_command("provision_pelican_servers", "--limit", "1")

        self.assertEqual(len(selected), 2)
        self.assertNotEqual(selected[0], selected[1])

    def test_customer_dashboard_only_lists_the_authenticated_customers_servers(self):
        from django.test import Client

        other_user = User.objects.create_user(
            username="other-customer",
            email="other@example.com",
            password="not-used-in-test",
            email_verified=True,
        )
        other_customer = Customer.objects.get(user=other_user)
        other_order = Order.objects.create(
            customer=other_customer,
            status=Order.Status.PAID,
            total_cents=0,
            idempotency_key="other-customer-order",
            paid_at=timezone.now(),
        )
        other_item = OrderItem.objects.create(
            order=other_order,
            plan=self.plan,
            product_name="Minecraft",
            plan_name="Other customer's server",
            description="",
            quantity=1,
            unit_price_cents=0,
            setup_fee_cents=0,
            line_total_cents=0,
            billing_interval_unit="once",
            billing_interval_count=1,
            resource_limits=self.plan.resource_limits,
        )
        PelicanServer.objects.create(
            order_item=other_item,
            quantity_index=1,
            customer=other_customer,
            external_id=f"phm-orderitem-{other_item.pk}",
        )

        client = Client()
        client.force_login(self.user)
        response = client.get("/servers/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(self.order.pk))
        self.assertNotContains(response, str(other_order.pk))



class FakeAccessSyncClient:
    def __init__(self, external_id, status=None):
        self.external_id = external_id
        self.status = status
        self.calls = []

    def get_server(self, panel_server_id):
        return {
            "id": panel_server_id,
            "external_id": self.external_id,
            "user": 55,
            "status": self.status,
        }

    def suspend_server(self, panel_server_id):
        self.calls.append(("suspend", panel_server_id))
        self.status = "suspended"

    def unsuspend_server(self, panel_server_id):
        self.calls.append(("unsuspend", panel_server_id))
        self.status = None


class PelicanServerAccessSyncTests(PelicanServerProvisioningFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.record.status = PelicanServer.Status.INSTALLED
        self.record.panel_server_id = 81
        self.record.save(update_fields=["status", "panel_server_id", "updated_at"])
        self.client = FakeAccessSyncClient(self.record.external_id)

    def make_order_active(self):
        self.order.status = Order.Status.PROVISIONING
        self.order.save(update_fields=["status", "updated_at"])
        self.order.status = Order.Status.ACTIVE
        self.order.save(update_fields=["status", "updated_at"])

    def test_active_one_time_order_is_not_suspended(self):
        from apps.pelican.services import sync_pelican_server_access

        self.make_order_active()
        result, should_suspend = sync_pelican_server_access(self.record.pk, client=self.client)
        self.assertFalse(should_suspend)
        self.assertEqual(self.client.calls, [])
        self.assertEqual(result.last_error_code, "")

    def test_non_active_order_is_suspended(self):
        from apps.pelican.services import sync_pelican_server_access

        result, should_suspend = sync_pelican_server_access(self.record.pk, client=self.client)
        self.assertTrue(should_suspend)
        self.assertEqual(self.client.calls, [("suspend", 81)])
        self.assertEqual(result.last_error_code, "")

    def test_already_suspended_server_is_not_toggled_again(self):
        from apps.pelican.services import sync_pelican_server_access

        self.client.status = "suspended"
        sync_pelican_server_access(self.record.pk, client=self.client)
        self.assertEqual(self.client.calls, [])

    def test_suspended_remote_server_is_unsuspended_for_active_order(self):
        from apps.pelican.services import sync_pelican_server_access

        self.make_order_active()
        self.client.status = "suspended"
        sync_pelican_server_access(self.record.pk, client=self.client)
        self.assertEqual(self.client.calls, [("unsuspend", 81)])

    def test_remote_owner_mismatch_is_recorded_and_retried(self):
        from apps.pelican.services import sync_pelican_server_access

        class WrongOwner(FakeAccessSyncClient):
            def get_server(self, panel_server_id):
                result = super().get_server(panel_server_id)
                result["user"] = 999
                return result

        self.make_order_active()
        wrong = WrongOwner(self.record.external_id)
        result, _should_suspend = sync_pelican_server_access(self.record.pk, client=wrong)
        self.assertEqual(result.last_error_code, "server_owner_mismatch")
        self.assertIsNotNone(result.next_retry_at)

    def test_api_failure_is_scheduled_for_retry(self):
        from apps.pelican.client import PelicanAPIError
        from apps.pelican.services import sync_pelican_server_access

        class BrokenClient(FakeAccessSyncClient):
            def get_server(self, panel_server_id):
                raise PelicanAPIError("http_503")

        broken = BrokenClient(self.record.external_id)
        result, _should_suspend = sync_pelican_server_access(self.record.pk, client=broken)
        self.assertEqual(result.last_error_code, "http_503")
        self.assertIsNotNone(result.next_retry_at)

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import HostingPlan, HostingProduct
from apps.wallet.models import LedgerSigningKey, Wallet
from apps.wallet.services import InsufficientFunds, credit_wallet
from apps.orders.models import Order
from apps.orders.services import (
    IdempotencyConflict,
    OrderError,
    OrderNotCancellable,
    cancel_pending_order,
    confirm_order_payment,
    place_order,
)


class OrderServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="order-customer",
            email="order-customer@example.com",
            password="secure-test-password",
        )
        self.wallet = self.user.customer.wallet
        self.product = HostingProduct.objects.create(
            name="Game Server",
            slug="game-server",
            is_active=True,
        )
        self.plan = HostingPlan.objects.create(
            product=self.product,
            name="Starter",
            slug="starter",
            price_cents=1200,
            setup_fee_cents=300,
            billing_interval_unit=HostingPlan.IntervalUnit.MONTH,
            billing_interval_count=1,
            resource_limits={"memory_mb": 4096},
            is_active=True,
        )
        self.key = LedgerSigningKey.objects.create(
            key_id="order-service-test-key",
            label="Order service test key",
            public_key=b"order-service-test-public-key",
            fingerprint="b" * 64,
        )
        self.signer = lambda payload: b"order-service-signature"

    def fund_wallet(self, amount=10000):
        credit_wallet(
            self.wallet.pk,
            amount,
            description="Order test funding",
            idempotency_key=f"order-test-funding-{amount}",
            signing_key_id=self.key.pk,
            signer=self.signer,
        )

    def test_place_order_reserves_funds_without_spending_them(self):
        self.fund_wallet()
        order = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="order-place-001",
        )
        self.wallet.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(order.total_cents, 1500)
        self.assertEqual(self.wallet.balance_cents, 10000)
        self.assertEqual(self.wallet.available_balance_cents, 8500)
        self.assertEqual(order.items.get().line_total_cents, 1500)

    def test_confirm_order_captures_hold_and_debits_wallet_once(self):
        self.fund_wallet()
        order = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="order-confirm-001",
        )
        paid = confirm_order_payment(
            order.pk,
            signing_key_id=self.key.pk,
            signer=self.signer,
        )
        repeated = confirm_order_payment(
            order.pk,
            signing_key_id=self.key.pk,
            signer=self.signer,
        )
        self.wallet.refresh_from_db()
        self.assertEqual(paid.status, Order.Status.PAID)
        self.assertEqual(repeated.pk, order.pk)
        self.assertEqual(self.wallet.balance_cents, 8500)
        self.assertEqual(self.wallet.transactions.filter(type="purchase").count(), 1)
        self.assertIsNotNone(paid.paid_transaction_id)

    def test_cancel_pending_order_releases_reserved_funds(self):
        self.fund_wallet()
        order = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="order-cancel-001",
        )
        cancelled = cancel_pending_order(order.pk)
        self.wallet.refresh_from_db()
        self.assertEqual(cancelled.status, Order.Status.CANCELLED)
        self.assertEqual(self.wallet.balance_cents, 10000)
        self.assertEqual(self.wallet.available_balance_cents, 10000)

    def test_insufficient_funds_rolls_back_order_and_hold(self):
        with self.assertRaises(InsufficientFunds):
            place_order(
                self.user.customer.pk,
                self.plan.pk,
                idempotency_key="order-insufficient-001",
            )
        self.assertFalse(Order.objects.exists())
        self.assertFalse(self.wallet.holds.exists())

    def test_idempotent_order_retry_returns_same_order(self):
        self.fund_wallet()
        first = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="order-idempotent-001",
        )
        second = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="order-idempotent-001",
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Order.objects.count(), 1)

    def test_idempotency_key_cannot_be_reused_for_another_plan(self):
        self.fund_wallet()
        first = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="order-conflict-001",
        )
        another = HostingPlan.objects.create(
            product=self.product,
            name="Plus",
            slug="plus",
            price_cents=2000,
            is_active=True,
        )
        with self.assertRaises(IdempotencyConflict):
            place_order(
                self.user.customer.pk,
                another.pk,
                idempotency_key="order-conflict-001",
            )

    def test_order_item_preserves_price_snapshot(self):
        self.fund_wallet()
        order = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="order-snapshot-001",
        )
        self.plan.price_cents = 5000
        self.plan.save(update_fields=["price_cents", "updated_at"])
        item = order.items.get()
        self.assertEqual(item.unit_price_cents, 1200)
        self.assertEqual(item.line_total_cents, 1500)
        self.assertEqual(order.total_cents, 1500)

    def test_free_plan_is_immediately_paid_without_zero_value_ledger_entry(self):
        free_plan = HostingPlan.objects.create(
            product=self.product,
            name="Free",
            slug="free",
            price_cents=0,
            billing_interval_unit=HostingPlan.IntervalUnit.ONCE,
            is_active=True,
        )
        order = place_order(
            self.user.customer.pk,
            free_plan.pk,
            idempotency_key="order-free-001",
        )
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertIsNone(order.wallet_hold_id)
        self.assertIsNone(order.paid_transaction_id)
        self.assertEqual(order.total_cents, 0)

    def test_inactive_plan_cannot_be_ordered(self):
        self.plan.is_active = False
        self.plan.save(update_fields=["is_active", "updated_at"])
        with self.assertRaises(OrderError):
            place_order(
                self.user.customer.pk,
                self.plan.pk,
                idempotency_key="order-inactive-001",
            )

    def test_paid_order_cannot_be_cancelled_without_refund_flow(self):
        self.fund_wallet()
        order = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="order-paid-cancel-001",
        )
        confirm_order_payment(
            order.pk,
            signing_key_id=self.key.pk,
            signer=self.signer,
        )
        with self.assertRaises(OrderNotCancellable):
            cancel_pending_order(order.pk)


class OrderAdminTests(TestCase):
    def test_orders_are_read_only_in_admin(self):
        admin_user = get_user_model().objects.create_superuser(
            username="order-admin",
            email="order-admin@example.com",
            password="secure-test-password",
        )
        self.client.force_login(admin_user)
        response = self.client.get("/admin/orders/order/")
        self.assertEqual(response.status_code, 200)

    def test_order_and_item_snapshots_cannot_be_rewritten(self):
        self.fund_wallet()
        order = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="order-immutable-001",
        )
        item = order.items.get()

        item.plan_name = "Changed plan"
        with self.assertRaises(TypeError):
            item.save()
        with self.assertRaises(TypeError):
            order.items.update(plan_name="Changed plan")

        order.total_cents = 1
        with self.assertRaises(TypeError):
            order.save(update_fields=["total_cents"])

    def test_invalid_order_state_transition_is_rejected(self):
        self.fund_wallet()
        order = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="order-transition-001",
        )
        order.status = Order.Status.ACTIVE
        with self.assertRaises(ValueError):
            order.save(update_fields=["status", "updated_at"])

    def test_database_rejects_mutation_of_order_history(self):
        from django.db import DatabaseError, connection, transaction

        self.fund_wallet()
        order = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="order-db-immutable-001",
        )
        item = order.items.get()

        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE order_items SET plan_name = %s WHERE id = %s",
                    ["Tampered", item.pk],
                )
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM order_items WHERE id = %s",
                    [item.pk],
                )
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM orders WHERE id = %s",
                    [str(order.pk)],
                )


class CustomerOrderViewsTests(TestCase):
    def setUp(self):
        import hashlib

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self.private_key = Ed25519PrivateKey.generate()
        public_key = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.user = get_user_model().objects.create_user(
            username="portal-customer",
            email="portal-customer@example.com",
            password="secure-test-password",
        )
        self.wallet = self.user.customer.wallet
        self.product = HostingProduct.objects.create(
            name="Portal Game Hosting",
            slug="portal-game-hosting",
            is_active=True,
        )
        self.plan = HostingPlan.objects.create(
            product=self.product,
            name="Portal Starter",
            slug="portal-starter",
            price_cents=1500,
            billing_interval_unit=HostingPlan.IntervalUnit.MONTH,
            is_active=True,
        )
        self.key = LedgerSigningKey.objects.create(
            key_id="portal-test-key",
            label="Portal test key",
            public_key=public_key,
            fingerprint=hashlib.sha256(public_key).hexdigest(),
            status=LedgerSigningKey.Status.ACTIVE,
        )
        self.client.force_login(self.user)

    def signed_settings(self):
        import base64

        from django.test import override_settings
        from cryptography.hazmat.primitives import serialization

        raw = self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return override_settings(
            WALLET_LEDGER_KEY_ID=self.key.key_id,
            WALLET_LEDGER_SIGNER="apps.wallet.signing.sign_payload",
            WALLET_LEDGER_PRIVATE_KEY_B64=base64.b64encode(raw).decode("ascii"),
        )

    def fund_wallet(self, amount=5000):
        from apps.wallet.services import credit_wallet

        credit_wallet(
            self.wallet.pk,
            amount,
            description="Portal test funding",
            idempotency_key=f"portal-funding-{amount}",
            signing_key_id=self.key.pk,
            signer=self.private_key.sign,
        )

    def test_catalog_shows_only_active_products_and_plans(self):
        inactive_product = HostingProduct.objects.create(
            name="Hidden",
            slug="hidden",
            is_active=False,
        )
        HostingPlan.objects.create(
            product=inactive_product,
            name="Hidden plan",
            slug="hidden-plan",
            price_cents=100,
            is_active=True,
        )
        inactive_plan = HostingPlan.objects.create(
            product=self.product,
            name="Hidden plan",
            slug="hidden-plan",
            price_cents=100,
            is_active=False,
        )

        response = self.client.get(reverse("catalog"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Portal Starter")
        self.assertNotContains(response, "Hidden plan")

    def test_customer_can_purchase_a_plan_using_wallet_balance(self):
        self.fund_wallet()
        key = "d5db8d5e-4ad4-4f50-8d8d-07f03fd45b42"
        with self.signed_settings():
            response = self.client.post(
                reverse("purchase_plan", args=[self.plan.pk]),
                {"idempotency_key": key},
            )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("orders"))
        order = Order.objects.get(customer=self.user.customer)
        self.wallet.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(order.total_cents, 1500)
        self.assertEqual(self.wallet.balance_cents, 3500)
        self.assertEqual(self.wallet.transactions.filter(type="purchase").count(), 1)

    def test_repeated_purchase_request_does_not_charge_twice(self):
        from django.urls import reverse

        self.fund_wallet()
        key = "c4bfc01e-07a4-4c28-97e0-99f6b3d2a8ad"
        with self.signed_settings():
            first = self.client.post(
                reverse("purchase_plan", args=[self.plan.pk]),
                {"idempotency_key": key},
            )
            second = self.client.post(
                reverse("purchase_plan", args=[self.plan.pk]),
                {"idempotency_key": key},
            )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_cents, 3500)
        self.assertEqual(Order.objects.filter(customer=self.user.customer).count(), 1)
        self.assertEqual(self.wallet.transactions.filter(type="purchase").count(), 1)

    def test_insufficient_wallet_balance_does_not_create_order_or_hold(self):
        from django.urls import reverse

        response = self.client.post(
            reverse("purchase_plan", args=[self.plan.pk]),
            {"idempotency_key": "1d5a1f86-8c35-49aa-9d40-6065f43a43d2"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Guthaben reicht")
        self.assertFalse(Order.objects.filter(customer=self.user.customer).exists())
        self.assertFalse(self.wallet.holds.exists())

    def test_customer_cannot_view_another_customers_order(self):
        from django.urls import reverse

        other_user = get_user_model().objects.create_user(
            username="other-portal-customer",
            email="other-portal@example.com",
            password="secure-test-password",
        )
        from apps.wallet.services import credit_wallet
        credit_wallet(
            other_user.customer.wallet.pk,
            5000,
            description="Other customer funding",
            idempotency_key="other-customer-funding-001",
            signing_key_id=self.key.pk,
            signer=self.private_key.sign,
        )
        other_order = place_order(
            other_user.customer.pk,
            self.plan.pk,
            idempotency_key="other-customer-order-001",
        )
        response = self.client.get(
            reverse("order_detail", args=[other_order.pk])
        )
        self.assertEqual(response.status_code, 404)

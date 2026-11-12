import calendar
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import HostingPlan, HostingProduct
from apps.orders.services import place_order, confirm_order_payment
from apps.wallet.models import LedgerSigningKey
from apps.wallet.services import credit_wallet

def fake_signer(payload):
    return b"test-signature"


from apps.subscriptions.models import Subscription
from apps.subscriptions.services import (
    SubscriptionNotDue,
    add_billing_interval,
    cancel_subscription,
    create_subscription_for_order_item,
    renew_subscription,
    set_auto_renew,
)


class SubscriptionServiceTests(TestCase):
    def setUp(self):
        self.private_key = None
        self.user = get_user_model().objects.create_user(
            username="subscription-customer",
            email="subscription-customer@example.com",
            password="secure-test-password",
        )
        self.wallet = self.user.customer.wallet
        self.product = HostingProduct.objects.create(
            name="Subscription Hosting",
            slug="subscription-hosting",
            is_active=True,
        )
        self.plan = HostingPlan.objects.create(
            product=self.product,
            name="Monthly",
            slug="monthly",
            price_cents=1200,
            setup_fee_cents=500,
            billing_interval_unit=HostingPlan.IntervalUnit.MONTH,
            billing_interval_count=1,
            is_active=True,
        )
        self.key = LedgerSigningKey.objects.create(
            key_id="subscription-test-key",
            label="Subscription test key",
            public_key=b"subscription-test-public-key",
            fingerprint="c" * 64,
        )
        self.signer = lambda payload: b"subscription-test-signature"
        self.client.force_login(self.user)

    def create_paid_subscription(self):
        credit_wallet(
            self.wallet.pk,
            5000,
            description="Subscription test funding",
            idempotency_key="subscription-test-funding",
            signing_key_id=self.key.pk,
            signer=self.signer,
        )
        order = place_order(
            self.user.customer.pk,
            self.plan.pk,
            idempotency_key="subscription-order-001",
        )
        paid = confirm_order_payment(
            order.pk,
            signing_key_id=self.key.pk,
            signer=self.signer,
        )
        return create_subscription_for_order_item(paid.items.get().pk)

    def test_month_interval_clamps_to_month_end(self):
        start = timezone.make_aware(datetime(2026, 1, 31, 12, 0))
        end = add_billing_interval(start, HostingPlan.IntervalUnit.MONTH, 1)
        self.assertEqual((end.year, end.month, end.day), (2026, 2, 28))

    def test_year_interval_handles_leap_day(self):
        start = timezone.make_aware(datetime(2024, 2, 29, 12, 0))
        end = add_billing_interval(start, HostingPlan.IntervalUnit.YEAR, 1)
        self.assertEqual((end.year, end.month, end.day), (2025, 2, 28))

    def test_subscription_uses_plan_price_without_one_time_setup_fee(self):
        subscription = self.create_paid_subscription()
        self.assertEqual(subscription.price_cents, 1200)
        self.assertEqual(subscription.price_eur, Decimal("12"))
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)
        self.assertFalse(subscription.auto_renew)

    def test_subscription_creation_is_idempotent(self):
        subscription = self.create_paid_subscription()
        repeated = create_subscription_for_order_item(subscription.order_item_id)
        self.assertEqual(subscription.pk, repeated.pk)
        self.assertEqual(Subscription.objects.count(), 1)

    def test_auto_renew_setting_requires_customer_ownership(self):
        subscription = self.create_paid_subscription()
        other = get_user_model().objects.create_user(
            username="other-subscription-customer",
            email="other-subscription@example.com",
            password="secure-test-password",
        )
        with self.assertRaises(Subscription.DoesNotExist):
            set_auto_renew(subscription.pk, other.customer.pk, True)
        enabled = set_auto_renew(subscription.pk, self.user.customer.pk, True)
        self.assertTrue(enabled.auto_renew)

    def test_renewal_debits_wallet_and_extends_period_once(self):
        subscription = self.create_paid_subscription()
        subscription = set_auto_renew(subscription.pk, self.user.customer.pk, True)
        wallet_before = self.wallet.balance_cents
        due_time = subscription.next_billing_at
        entry = renew_subscription(
            subscription.pk,
            signing_key_id=self.key.pk,
            signer=self.signer,
            now=due_time,
        )
        subscription.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(entry.amount_cents, -1200)
        self.assertEqual(self.wallet.balance_cents, wallet_before - 1200)
        self.assertGreater(subscription.next_billing_at, due_time)
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)

    def test_renewal_is_not_run_before_due_date(self):
        subscription = self.create_paid_subscription()
        set_auto_renew(subscription.pk, self.user.customer.pk, True)
        with self.assertRaises(SubscriptionNotDue):
            renew_subscription(
                subscription.pk,
                signing_key_id=self.key.pk,
                signer=self.signer,
                now=subscription.next_billing_at - timedelta(days=1),
            )

    def test_insufficient_balance_marks_subscription_past_due_without_debit(self):
        from apps.wallet.services import debit_wallet

        subscription = self.create_paid_subscription()
        set_auto_renew(subscription.pk, self.user.customer.pk, True)
        self.wallet.refresh_from_db()
        debit_wallet(
            self.wallet.pk,
            self.wallet.balance_cents,
            description="Spend remaining test balance",
            idempotency_key="subscription-spend-remaining",
            signing_key_id=self.key.pk,
            signer=self.signer,
        )
        self.wallet.refresh_from_db()
        balance_before = self.wallet.balance_cents
        result = renew_subscription(
            subscription.pk,
            signing_key_id=self.key.pk,
            signer=self.signer,
            now=subscription.next_billing_at,
        )
        subscription.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertIsNone(result)
        self.assertEqual(subscription.status, Subscription.Status.PAST_DUE)
        self.assertEqual(self.wallet.balance_cents, balance_before)
        self.assertIsNotNone(subscription.past_due_since)

    def test_customer_can_enable_and_disable_own_auto_renewal(self):
        subscription = self.create_paid_subscription()
        response = self.client.post(
            reverse("subscription_action", args=[subscription.pk]),
            {"action": "enable_auto_renew"},
        )
        self.assertRedirects(response, reverse("subscriptions"))
        subscription.refresh_from_db()
        self.assertTrue(subscription.auto_renew)

        self.client.post(
            reverse("subscription_action", args=[subscription.pk]),
            {"action": "disable_auto_renew"},
        )
        subscription.refresh_from_db()
        self.assertFalse(subscription.auto_renew)

    def test_customer_can_schedule_cancellation_at_period_end(self):
        subscription = self.create_paid_subscription()
        self.client.post(
            reverse("subscription_action", args=[subscription.pk]),
            {"action": "cancel_at_period_end"},
        )
        subscription.refresh_from_db()
        self.assertTrue(subscription.cancel_at_period_end)
        self.assertFalse(subscription.auto_renew)
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)

    def test_customer_cannot_change_another_customers_subscription(self):
        other = get_user_model().objects.create_user(
            username="subscription-view-other",
            email="subscription-view-other@example.com",
            password="secure-test-password",
        )
        credit_wallet(
            other.customer.wallet.pk,
            5000,
            description="Other subscription funding",
            idempotency_key="other-subscription-view-funding",
            signing_key_id=self.key.pk,
            signer=self.signer,
        )
        order = place_order(
            other.customer.pk,
            self.plan.pk,
            idempotency_key="other-subscription-view-order",
        )
        paid = confirm_order_payment(
            order.pk,
            signing_key_id=self.key.pk,
            signer=self.signer,
        )
        subscription = Subscription.objects.get(order_item=paid.items.get())
        response = self.client.post(
            reverse("subscription_action", args=[subscription.pk]),
            {"action": "enable_auto_renew"},
        )
        self.assertRedirects(response, reverse("subscriptions"))
        subscription.refresh_from_db()
        self.assertFalse(subscription.auto_renew)

    def test_renewal_command_processes_due_opted_in_subscriptions(self):
        from datetime import timedelta
        from django.core.management import call_command
        from django.test import override_settings

        subscription = self.create_paid_subscription()
        set_auto_renew(subscription.pk, self.user.customer.pk, True)
        due = timezone.now() - timedelta(days=1)
        subscription.current_period_end = due
        subscription.next_billing_at = due
        subscription.save(update_fields=["current_period_end", "next_billing_at", "updated_at"])

        balance_before = self.wallet.balance_cents
        with override_settings(
            WALLET_LEDGER_KEY_ID=self.key.key_id,
            WALLET_LEDGER_SIGNER="apps.subscriptions.tests.fake_signer",
        ):
            call_command("process_subscription_renewals")

        subscription.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)
        self.assertGreater(subscription.next_billing_at, timezone.now())
        self.assertEqual(self.wallet.balance_cents, balance_before - subscription.price_cents)

    def test_renewal_command_expires_non_auto_renewing_contracts(self):
        from datetime import timedelta
        from django.core.management import call_command

        subscription = self.create_paid_subscription()
        due = timezone.now() - timedelta(days=1)
        subscription.current_period_end = due
        subscription.next_billing_at = due
        subscription.save(update_fields=["current_period_end", "next_billing_at", "updated_at"])

        call_command("process_subscription_renewals")
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, Subscription.Status.EXPIRED)

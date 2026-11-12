import calendar
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import HostingPlan
from apps.customers.models import Customer
from apps.orders.models import Order, OrderItem
from apps.wallet.models import Wallet
from apps.wallet.services import InsufficientFunds, debit_wallet

from .models import Subscription


class SubscriptionError(Exception):
    pass


class SubscriptionNotDue(SubscriptionError):
    pass


class SubscriptionNotRenewable(SubscriptionError):
    pass


def add_billing_interval(value, unit, count):
    """Add a calendar-aware interval without overflowing month-end dates."""
    if count < 1:
        raise ValueError("Billing interval count must be positive.")
    if unit == HostingPlan.IntervalUnit.DAY:
        return value + timedelta(days=count)
    if unit == HostingPlan.IntervalUnit.WEEK:
        return value + timedelta(weeks=count)
    if unit == HostingPlan.IntervalUnit.MONTH:
        month_index = value.year * 12 + value.month - 1 + count
        year, month_zero = divmod(month_index, 12)
        month = month_zero + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return value.replace(year=year, month=month, day=day)
    if unit == HostingPlan.IntervalUnit.YEAR:
        year = value.year + count
        day = min(value.day, calendar.monthrange(year, value.month)[1])
        return value.replace(year=year, day=day)
    raise ValueError("One-time products do not have subscription billing intervals.")


@transaction.atomic
def create_subscription_for_order_item(order_item_id):
    """Create a recurring subscription once a matching order has been paid."""
    item = (
        OrderItem.objects.select_for_update()
        .select_related("order__customer", "plan")
        .get(pk=order_item_id)
    )
    if item.order.status != Order.Status.PAID:
        raise SubscriptionError("A subscription can only be created from a paid order.")
    if item.billing_interval_unit == HostingPlan.IntervalUnit.ONCE:
        return None

    existing = Subscription.objects.filter(order_item=item).first()
    if existing:
        return existing

    start = item.order.paid_at or timezone.now()
    end = add_billing_interval(
        start,
        item.billing_interval_unit,
        item.billing_interval_count,
    )
    return Subscription.objects.create(
        customer=item.order.customer,
        order_item=item,
        plan=item.plan,
        status=Subscription.Status.ACTIVE,
        currency="EUR",
        price_cents=item.unit_price_cents,
        billing_interval_unit=item.billing_interval_unit,
        billing_interval_count=item.billing_interval_count,
        current_period_start=start,
        current_period_end=end,
        next_billing_at=end,
        auto_renew=False,
    )


@transaction.atomic
def set_auto_renew(subscription_id, customer_id, enabled: bool) -> Subscription:
    if type(enabled) is not bool:
        raise SubscriptionError("Auto-renew must be a boolean.")
    subscription = Subscription.objects.select_for_update().get(
        pk=subscription_id,
        customer_id=customer_id,
    )
    if subscription.status not in (Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE):
        raise SubscriptionError("Only active or past-due subscriptions can change renewal settings.")
    if subscription.cancel_at_period_end and enabled:
        raise SubscriptionError("A subscription scheduled for cancellation cannot enable renewal.")
    subscription.auto_renew = enabled
    subscription.save(update_fields=["auto_renew", "updated_at"])
    return subscription


@transaction.atomic
def cancel_subscription(
    subscription_id,
    customer_id,
    *,
    at_period_end: bool = True,
) -> Subscription:
    subscription = Subscription.objects.select_for_update().get(
        pk=subscription_id,
        customer_id=customer_id,
    )
    if subscription.status in (Subscription.Status.CANCELLED, Subscription.Status.EXPIRED):
        return subscription
    if at_period_end:
        subscription.auto_renew = False
        subscription.cancel_at_period_end = True
    else:
        subscription.status = Subscription.Status.CANCELLED
        subscription.cancelled_at = timezone.now()
        subscription.auto_renew = False
        subscription.cancel_at_period_end = False
    subscription.save(update_fields=[
        "status",
        "cancelled_at",
        "auto_renew",
        "cancel_at_period_end",
        "updated_at",
    ])
    return subscription


@transaction.atomic
def renew_subscription(
    subscription_id,
    *,
    signing_key_id,
    signer,
    now=None,
):
    """Renew one due subscription using its customer's wallet, never an external provider."""
    now = now or timezone.now()
    subscription = Subscription.objects.select_for_update().select_related(
        "customer"
    ).get(pk=subscription_id)

    if subscription.status not in (Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE):
        raise SubscriptionNotRenewable("This subscription is not renewable.")
    if not subscription.auto_renew or subscription.cancel_at_period_end:
        raise SubscriptionNotRenewable("Automatic renewal is not enabled.")
    if subscription.next_billing_at > now:
        raise SubscriptionNotDue("The next billing date has not arrived.")

    wallet = Wallet.objects.select_for_update().get(customer=subscription.customer)
    transaction_entry = None
    if subscription.price_cents > 0:
        idempotency_key = (
            f"subscription-renewal:{subscription.pk}:"
            f"{subscription.next_billing_at.isoformat()}"
        )
        try:
            transaction_entry = debit_wallet(
                wallet.pk,
                subscription.price_cents,
                description=f"Subscription renewal {subscription.pk}",
                idempotency_key=idempotency_key,
                signing_key_id=signing_key_id,
                signer=signer,
                reference=str(subscription.pk),
                metadata={"source": "subscription_renewal", "subscription_id": str(subscription.pk)},
            )
        except InsufficientFunds:
            subscription.status = Subscription.Status.PAST_DUE
            subscription.past_due_since = subscription.past_due_since or now
            subscription.last_renewal_attempt_at = now
            subscription.save(update_fields=[
                "status",
                "past_due_since",
                "last_renewal_attempt_at",
                "updated_at",
            ])
            return None

    period_start = max(subscription.current_period_end, now)
    period_end = add_billing_interval(
        period_start,
        subscription.billing_interval_unit,
        subscription.billing_interval_count,
    )
    subscription.status = Subscription.Status.ACTIVE
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end
    subscription.next_billing_at = period_end
    subscription.past_due_since = None
    subscription.last_renewal_attempt_at = now
    subscription.last_renewed_at = now
    subscription.save(update_fields=[
        "status",
        "current_period_start",
        "current_period_end",
        "next_billing_at",
        "past_due_since",
        "last_renewal_attempt_at",
        "last_renewed_at",
        "updated_at",
    ])
    return transaction_entry


@transaction.atomic
def expire_subscription(subscription_id, *, now=None):
    now = now or timezone.now()
    subscription = Subscription.objects.select_for_update().get(pk=subscription_id)
    if subscription.status in (Subscription.Status.CANCELLED, Subscription.Status.EXPIRED):
        return subscription
    if subscription.current_period_end > now:
        raise SubscriptionNotDue("The current subscription period has not ended.")
    if subscription.cancel_at_period_end:
        subscription.status = Subscription.Status.CANCELLED
        subscription.cancelled_at = now
    else:
        subscription.status = Subscription.Status.EXPIRED
    subscription.auto_renew = False
    subscription.save(update_fields=["status", "cancelled_at", "auto_renew", "updated_at"])
    return subscription

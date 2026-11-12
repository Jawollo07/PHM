from django.db import transaction
from django.utils import timezone

from apps.catalog.models import HostingPlan
from apps.customers.models import Customer
from apps.wallet.models import Wallet
from apps.wallet.services import (
    HoldNotActive,
    IdempotencyConflict,
    InsufficientFunds,
    capture_hold,
    place_hold,
    release_hold,
)

from .models import Order, OrderItem


class OrderError(Exception):
    pass


class OrderNotPayable(OrderError):
    pass


class OrderNotCancellable(OrderError):
    pass


@transaction.atomic
def place_order(
    customer_id,
    plan_id,
    *,
    idempotency_key: str,
    quantity: int = 1,
) -> Order:
    """Create an order, snapshot its plan, and reserve wallet funds atomically."""
    if type(quantity) is not int or quantity < 1:
        raise OrderError("Order quantity must be a positive integer.")
    idempotency_key = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
    if not idempotency_key or len(idempotency_key) > 128:
        raise OrderError("A valid order idempotency key is required.")

    customer = Customer.objects.select_for_update().get(pk=customer_id)
    if customer.status != Customer.Status.ACTIVE:
        raise OrderError("Only active personal customer accounts may place orders.")

    existing = Order.objects.filter(
        customer=customer,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        item = existing.items.first()
        if item is None or str(item.plan_id) != str(plan_id) or item.quantity != quantity:
            raise IdempotencyConflict("The order idempotency key was already used for another request.")
        return existing

    plan = (
        HostingPlan.objects.select_for_update()
        .select_related("product")
        .get(pk=plan_id)
    )
    if not plan.is_active or not plan.product.is_active:
        raise OrderError("This hosting plan is not available for purchase.")

    line_total = (plan.price_cents + plan.setup_fee_cents) * quantity
    if line_total > 9_223_372_036_854_775_807:
        raise OrderError("The order total exceeds the supported EUR-cent range.")

    is_free = line_total == 0
    order = Order.objects.create(
        customer=customer,
        status=Order.Status.PAID if is_free else Order.Status.PENDING_PAYMENT,
        total_cents=line_total,
        idempotency_key=idempotency_key,
        paid_at=timezone.now() if is_free else None,
    )
    OrderItem.objects.create(
        order=order,
        plan=plan,
        product_name=plan.product.name,
        plan_name=plan.name,
        description=plan.description,
        quantity=quantity,
        unit_price_cents=plan.price_cents,
        setup_fee_cents=plan.setup_fee_cents,
        line_total_cents=line_total,
        billing_interval_unit=plan.billing_interval_unit,
        billing_interval_count=plan.billing_interval_count,
        resource_limits=plan.resource_limits,
    )

    if not is_free:
        wallet = Wallet.objects.select_for_update().get(customer=customer)
        hold = place_hold(
            wallet.pk,
            amount_cents=line_total,
            idempotency_key=f"order:{order.pk}:hold",
            reference=str(order.pk),
            metadata={"source": "phm_order", "order_id": str(order.pk)},
        )
        order.wallet_hold = hold
        order.save(update_fields=["wallet_hold", "updated_at"])
    return order


@transaction.atomic
def confirm_order_payment(order_id, *, signing_key_id, signer) -> Order:
    """Capture the reserved wallet amount and append its signed purchase entry."""
    order = Order.objects.select_for_update().select_related("wallet_hold").get(pk=order_id)
    if order.status == Order.Status.PAID:
        return order
    if order.status != Order.Status.PENDING_PAYMENT or order.wallet_hold_id is None:
        raise OrderNotPayable("This order is not awaiting wallet payment.")

    entry = capture_hold(
        order.wallet_hold_id,
        signing_key_id=signing_key_id,
        signer=signer,
    )
    if entry is None:
        order.status = Order.Status.FAILED
        order.save(update_fields=["status", "updated_at"])
        return order

    order.status = Order.Status.PAID
    order.paid_transaction = entry
    order.paid_at = timezone.now()
    order.save(update_fields=["status", "paid_transaction", "paid_at", "updated_at"])
    return order


@transaction.atomic
def cancel_pending_order(order_id) -> Order:
    """Cancel an unpaid order and release its wallet reservation."""
    order = Order.objects.select_for_update().select_related("wallet_hold").get(pk=order_id)
    if order.status == Order.Status.CANCELLED:
        return order
    if order.status != Order.Status.PENDING_PAYMENT:
        raise OrderNotCancellable("Only unpaid pending orders can be cancelled.")
    if order.wallet_hold_id:
        release_hold(order.wallet_hold_id)
    order.status = Order.Status.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    return order

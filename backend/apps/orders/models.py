import uuid

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class OrderQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Orders must be changed through order services.")

    def bulk_update(self, objs, fields, **kwargs):
        raise TypeError("Orders must be changed through order services.")

    def delete(self):
        raise TypeError("Orders cannot be deleted; preserve the order history.")


class OrderManager(models.Manager.from_queryset(OrderQuerySet)):
    pass


class ImmutableOrderItemQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Order item snapshots are immutable.")

    def bulk_update(self, objs, fields, **kwargs):
        raise TypeError("Order item snapshots are immutable.")

    def bulk_create(self, objs, **kwargs):
        raise TypeError("Order items must be created through order services.")

    def delete(self):
        raise TypeError("Order item snapshots cannot be deleted.")


class ImmutableOrderItemManager(models.Manager.from_queryset(ImmutableOrderItemQuerySet)):
    pass


class Order(models.Model):
    """A private customer's wallet-funded purchase order."""

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Wartet auf Guthabenbuchung"
        PAID = "paid", "Bezahlt"
        PROVISIONING = "provisioning", "Wird bereitgestellt"
        ACTIVE = "active", "Aktiv"
        CANCELLED = "cancelled", "Storniert"
        FAILED = "failed", "Fehlgeschlagen"

    ALLOWED_TRANSITIONS = {
        Status.PENDING_PAYMENT: {Status.PAID, Status.CANCELLED, Status.FAILED},
        Status.PAID: {Status.PROVISIONING, Status.FAILED},
        Status.PROVISIONING: {Status.ACTIVE, Status.FAILED},
        Status.ACTIVE: set(),
        Status.CANCELLED: set(),
        Status.FAILED: set(),
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
    )
    currency = models.CharField(max_length=3, default="EUR", editable=False)
    total_cents = models.BigIntegerField(validators=[MinValueValidator(0)])
    idempotency_key = models.CharField(max_length=128)
    wallet_hold = models.OneToOneField(
        "wallet.WalletHold",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="order",
    )
    paid_transaction = models.OneToOneField(
        "wallet.WalletTransaction",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="paid_order",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrderManager()

    class Meta:
        db_table = "orders"
        ordering = ["-created_at"]
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "idempotency_key"],
                name="order_customer_idempotency_unique",
            ),
            models.CheckConstraint(
                condition=Q(total_cents__gte=0),
                name="order_total_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(currency="EUR"),
                name="order_currency_eur",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="paid", paid_at__isnull=False)
                    | ~Q(status="paid")
                ),
                name="order_paid_requires_timestamp",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="paid", total_cents=0, paid_transaction__isnull=True)
                    | Q(status="paid", total_cents__gt=0, paid_transaction__isnull=False)
                    | ~Q(status="paid")
                ),
                name="order_paid_payment_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["customer", "status", "created_at"], name="order_customer_status_idx"),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding:
            return super().save(*args, **kwargs)

        original = type(self).objects.get(pk=self.pk)
        immutable_fields = (
            "customer_id",
            "currency",
            "total_cents",
            "idempotency_key",
            "created_at",
        )
        if any(getattr(original, field) != getattr(self, field) for field in immutable_fields):
            raise TypeError("Order ownership, price and idempotency data are immutable.")
        if original.status != self.status:
            if self.status not in self.ALLOWED_TRANSITIONS[original.status]:
                raise ValueError(
                    f"Invalid order state transition: {original.status} -> {self.status}."
                )
        if original.wallet_hold_id and original.wallet_hold_id != self.wallet_hold_id:
            raise TypeError("An order wallet hold cannot be replaced.")
        if original.paid_transaction_id and original.paid_transaction_id != self.paid_transaction_id:
            raise TypeError("An order payment transaction cannot be replaced.")
        if self.status == self.Status.PAID:
            if self.paid_at is None:
                raise ValueError("Paid orders require a paid_at timestamp.")
            if self.total_cents > 0 and self.paid_transaction_id is None:
                raise ValueError("Paid orders require a signed wallet transaction.")
            if self.total_cents == 0 and self.paid_transaction_id is not None:
                raise ValueError("Free orders cannot have a zero-value wallet transaction.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Orders cannot be deleted; preserve the order history.")

    def __str__(self):
        return f"Order {self.pk} ({self.status})"


class OrderItem(models.Model):
    """Immutable plan and price snapshot taken when the order is placed."""

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="items")
    plan = models.ForeignKey(
        "catalog.HostingPlan",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=120)
    plan_name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    unit_price_cents = models.BigIntegerField(validators=[MinValueValidator(0)])
    setup_fee_cents = models.BigIntegerField(default=0, validators=[MinValueValidator(0)])
    line_total_cents = models.BigIntegerField(validators=[MinValueValidator(0)])
    billing_interval_unit = models.CharField(max_length=10)
    billing_interval_count = models.PositiveSmallIntegerField(default=1)
    resource_limits = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableOrderItemManager()

    class Meta:
        db_table = "order_items"
        verbose_name = "Order item"
        verbose_name_plural = "Order items"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="order_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(unit_price_cents__gte=0),
                name="order_item_unit_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(setup_fee_cents__gte=0),
                name="order_item_setup_fee_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(line_total_cents__gte=0),
                name="order_item_total_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(billing_interval_count__gte=1),
                name="order_item_interval_positive",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Order item snapshots are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Order item snapshots cannot be deleted.")

    def __str__(self):
        return f"{self.product_name} – {self.plan_name} × {self.quantity}"

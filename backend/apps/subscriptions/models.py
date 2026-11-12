import uuid

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q


class SubscriptionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Subscriptions must be changed through subscription services.")

    def bulk_update(self, objs, fields, **kwargs):
        raise TypeError("Subscriptions must be changed through subscription services.")

    def delete(self):
        raise TypeError("Subscription history cannot be deleted.")


class SubscriptionManager(models.Manager.from_queryset(SubscriptionQuerySet)):
    pass


class Subscription(models.Model):
    """A private customer's recurring hosting contract, funded by the PHM wallet."""

    class IntervalUnit(models.TextChoices):
        DAY = "day", "Tag(e)"
        WEEK = "week", "Woche(n)"
        MONTH = "month", "Monat(e)"
        YEAR = "year", "Jahr(e)"

    class Status(models.TextChoices):
        ACTIVE = "active", "Aktiv"
        PAST_DUE = "past_due", "Guthaben ausstehend"
        SUSPENDED = "suspended", "Pausiert"
        CANCELLED = "cancelled", "Gekündigt"
        EXPIRED = "expired", "Abgelaufen"

    ALLOWED_TRANSITIONS = {
        Status.ACTIVE: {Status.PAST_DUE, Status.SUSPENDED, Status.CANCELLED, Status.EXPIRED},
        Status.PAST_DUE: {Status.ACTIVE, Status.SUSPENDED, Status.CANCELLED, Status.EXPIRED},
        Status.SUSPENDED: {Status.ACTIVE, Status.CANCELLED, Status.EXPIRED},
        Status.CANCELLED: set(),
        Status.EXPIRED: set(),
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    order_item = models.OneToOneField(
        "orders.OrderItem",
        on_delete=models.PROTECT,
        related_name="subscription",
    )
    plan = models.ForeignKey(
        "catalog.HostingPlan",
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    currency = models.CharField(max_length=3, default="EUR", editable=False)
    price_cents = models.BigIntegerField(validators=[MinValueValidator(0)])
    billing_interval_unit = models.CharField(
        max_length=10,
        choices=IntervalUnit.choices,
    )
    billing_interval_count = models.PositiveSmallIntegerField(default=1)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    next_billing_at = models.DateTimeField()
    auto_renew = models.BooleanField(default=False)
    cancel_at_period_end = models.BooleanField(default=False)
    past_due_since = models.DateTimeField(null=True, blank=True)
    last_renewal_attempt_at = models.DateTimeField(null=True, blank=True)
    last_renewed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SubscriptionManager()

    class Meta:
        db_table = "subscriptions"
        ordering = ["-created_at"]
        verbose_name = "Subscription"
        verbose_name_plural = "Subscriptions"
        constraints = [
            models.CheckConstraint(
                condition=Q(currency="EUR"),
                name="subscription_currency_eur",
            ),
            models.CheckConstraint(
                condition=Q(price_cents__gte=0),
                name="subscription_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(billing_interval_count__gte=1),
                name="subscription_interval_positive",
            ),
            models.CheckConstraint(
                condition=Q(current_period_end__gt=F("current_period_start")),
                name="subscription_period_order_valid",
            ),
            models.CheckConstraint(
                condition=Q(status="cancelled", cancelled_at__isnull=False) | ~Q(status="cancelled"),
                name="subscription_cancel_requires_timestamp",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "next_billing_at"],
                name="subscription_due_idx",
            ),
            models.Index(
                fields=["customer", "status"],
                name="subscription_customer_status_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding:
            return super().save(*args, **kwargs)

        original = type(self).objects.get(pk=self.pk)
        immutable_fields = (
            "customer_id",
            "order_item_id",
            "plan_id",
            "currency",
            "price_cents",
            "billing_interval_unit",
            "billing_interval_count",
            "created_at",
        )
        if any(getattr(original, field) != getattr(self, field) for field in immutable_fields):
            raise TypeError("Subscription ownership and billing terms are immutable.")
        if original.status != self.status:
            if self.status not in self.ALLOWED_TRANSITIONS[original.status]:
                raise ValueError(
                    f"Invalid subscription state transition: {original.status} -> {self.status}."
                )
        if self.status == self.Status.CANCELLED and self.cancelled_at is None:
            raise ValueError("Cancelled subscriptions require a cancellation timestamp.")
        if self.current_period_end <= self.current_period_start:
            raise ValueError("Subscription period end must be after its start.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Subscription history cannot be deleted.")

    @property
    def price_eur(self):
        from decimal import Decimal
        return Decimal(self.price_cents) / Decimal("100")

    def __str__(self):
        return f"Subscription {self.pk} ({self.status})"

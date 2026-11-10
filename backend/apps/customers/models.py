
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


# ============================================================
# Customer
# ============================================================

class Customer(models.Model):
    """
    Personal customer account.

    Every registered user has exactly one customer account.
    The customer owns exactly one wallet.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        ARCHIVED = "archived", "Archived"
        BANNED = "banned", "Banned"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="customer",
    )

    phone_number = models.CharField(
        max_length=30,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    suspended_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    suspension_reason = models.TextField(
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "customers"
        verbose_name = "Customer"
        verbose_name_plural = "Customers"
        ordering = ["-created_at"]

        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="customer_status_created_idx",
            ),
        ]

    def __str__(self):
        return f"Customer {self.id} ({self.user.email})"

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE


# ============================================================
# Customer Addresses
# ============================================================

class CustomerAddress(models.Model):
    """
    Stores personal customer addresses.

    A customer can have multiple addresses, for example
    separate billing and contact addresses.
    """

    class Type(models.TextChoices):
        BILLING = "billing", "Billing"
        CONTACT = "contact", "Contact"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="addresses",
    )

    address_type = models.CharField(
        max_length=20,
        choices=Type.choices,
    )

    recipient_name = models.CharField(
        max_length=255,
    )

    company_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    street = models.CharField(
        max_length=255,
    )

    house_number = models.CharField(
        max_length=30,
        blank=True,
    )

    address_line_2 = models.CharField(
        max_length=255,
        blank=True,
    )

    postal_code = models.CharField(
        max_length=20,
    )

    city = models.CharField(
        max_length=120,
    )

    state = models.CharField(
        max_length=120,
        blank=True,
    )

    country = models.CharField(
        max_length=64,
        default="Germany",
    )

    is_default = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "customer_addresses"
        verbose_name = "Customer Address"
        verbose_name_plural = "Customer Addresses"
        ordering = ["-is_default", "created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["customer", "address_type"],
                condition=Q(is_default=True),
                name="customer_unique_default_address",
            ),
        ]

        indexes = [
            models.Index(
                fields=["customer", "address_type"],
                name="customer_address_type_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.recipient_name}, "
            f"{self.street} {self.house_number}, "
            f"{self.postal_code} {self.city}"
        )


# ============================================================
# Customer Settings
# ============================================================

class CustomerSettings(models.Model):
    """
    Individual preferences for a customer account.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    customer = models.OneToOneField(
        Customer,
        on_delete=models.CASCADE,
        related_name="settings",
    )

    language = models.CharField(
        max_length=10,
        default="de",
    )

    # Notification preferences
    email_notifications = models.BooleanField(
        default=True,
    )

    service_notifications = models.BooleanField(
        default=True,
    )

    payment_notifications = models.BooleanField(
        default=True,
    )

    security_notifications = models.BooleanField(
        default=True,
    )

    marketing_emails = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "customer_settings"
        verbose_name = "Customer Settings"
        verbose_name_plural = "Customer Settings"

    def __str__(self):
        return f"Settings for {self.customer_id}" # type: ignore

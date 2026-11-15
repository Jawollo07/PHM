import uuid

from django.db import models


class PelicanAccount(models.Model):
    """Durable link between one verified PHM customer and one Pelican user."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        LINKED = "linked", "Linked"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.OneToOneField(
        "customers.Customer", on_delete=models.PROTECT, related_name="pelican_account"
    )
    panel_user_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)
    panel_email = models.EmailField(blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    linked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pelican_accounts"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(status="linked", panel_user_id__isnull=False)
                           | ~models.Q(status="linked")),
                name="pelican_linked_requires_panel_id",
            ),
        ]

    def __str__(self):
        return f"Pelican account for customer {self.customer_id} ({self.status})"


class PelicanServer(models.Model):
    """One independently provisioned Pelican server per ordered unit."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROVISIONING = "provisioning", "Provisioning"
        INSTALLING = "installing", "Installing"
        INSTALLED = "installed", "Installed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_item = models.ForeignKey(
        "orders.OrderItem", on_delete=models.PROTECT, related_name="pelican_servers"
    )
    quantity_index = models.PositiveIntegerField(default=1)
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="pelican_servers"
    )
    external_id = models.CharField(max_length=255, unique=True, editable=False)
    panel_server_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)
    panel_uuid = models.CharField(max_length=64, blank=True, default="")
    panel_identifier = models.CharField(max_length=32, blank=True, default="")
    panel_name = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    provisioned_at = models.DateTimeField(null=True, blank=True)
    installed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pelican_servers"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["order_item", "quantity_index"],
                name="pelican_item_unit_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity_index__gte=1),
                name="pelican_unit_index_positive",
            ),
            models.CheckConstraint(
                condition=(models.Q(status__in=["installing", "installed"],
                                    panel_server_id__isnull=False)
                           | ~models.Q(status__in=["installing", "installed"])),
                name="pelican_server_remote_id_required",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "last_attempt_at", "created_at"],
                         name="pelican_server_queue_idx"),
            models.Index(fields=["customer", "status"], name="pelican_customer_status_idx"),
        ]

    def __str__(self):
        return f"Pelican server {self.external_id} ({self.status})"

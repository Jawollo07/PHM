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

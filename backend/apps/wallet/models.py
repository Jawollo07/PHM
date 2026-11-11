
import uuid

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


GENESIS_HASH = "0" * 64


# ============================================================
# Immutable QuerySet
# ============================================================

class ImmutableQuerySet(models.QuerySet):
    """
    Prevent normal ORM operations from modifying or deleting
    immutable ledger records.

    Database-level protection is still required against raw SQL.
    """

    def update(self, **kwargs):
        raise TypeError("Ledger records cannot be updated.")

    def delete(self):
        raise TypeError("Ledger records cannot be deleted.")

    def bulk_update(self, objs, fields, **kwargs): # type: ignore
        raise TypeError("Ledger records cannot be bulk-updated.")

    def bulk_create(self, objs, **kwargs): # type: ignore
        raise TypeError(
            "Ledger records must be created through the ledger service."
        )


class ImmutableManager(models.Manager.from_queryset(ImmutableQuerySet)):
    pass


class WalletQuerySet(models.QuerySet):
    def delete(self):
        raise TypeError("Wallets cannot be deleted; archive the customer instead.")


class WalletManager(models.Manager.from_queryset(WalletQuerySet)):
    pass


# ============================================================
# Wallet
# ============================================================

class Wallet(models.Model):
    objects = WalletManager()

    """
    One financial wallet per customer.

    All amounts are stored in EUR cents.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    customer = models.OneToOneField(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="wallet",
    )

    currency = models.CharField(
        max_length=3,
        default="EUR",
        editable=False,
    )

    balance_cents = models.BigIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "wallets"
        verbose_name = "Wallet"
        verbose_name_plural = "Wallets"

        constraints = [
            models.CheckConstraint(
                condition=Q(balance_cents__gte=0),
                name="wallet_balance_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(currency="EUR"),
                name="wallet_currency_eur",
            ),
        ]

    @property
    def reserved_balance_cents(self):
        return self.holds.filter(
            status=WalletHold.Status.ACTIVE
        ).aggregate(
            total=models.Sum("amount_cents")
        )["total"] or 0

    @property
    def available_balance_cents(self):
        return (
            self.balance_cents
            - self.reserved_balance_cents
        )

    def delete(self, *args, **kwargs):
        raise TypeError("Wallets cannot be deleted; archive the customer instead.")

    def __str__(self):
        return f"Wallet {self.id}"


# ============================================================
# Ledger Signing Keys
# ============================================================

class LedgerSigningKey(models.Model):
    """
    Public signing key registry.

    IMPORTANT:
    Private keys must NEVER be stored in this database.
    Keep them in a separate signing service or secret manager.
    """

    class Algorithm(models.TextChoices):
        ED25519 = "ed25519", "Ed25519"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"
        REVOKED = "revoked", "Revoked"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    key_id = models.CharField(
        max_length=64,
        unique=True,
    )

    label = models.CharField(
        max_length=100,
    )

    algorithm = models.CharField(
        max_length=20,
        choices=Algorithm.choices,
        default=Algorithm.ED25519,
    )

    public_key = models.BinaryField()

    fingerprint = models.CharField(
        max_length=64,
        unique=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    activated_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    retired_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "ledger_signing_keys"
        verbose_name = "Ledger Signing Key"
        verbose_name_plural = "Ledger Signing Keys"

        constraints = [
            models.CheckConstraint(
                condition=Q(algorithm="ed25519"),
                name="ledger_key_algorithm_ed25519",
            ),
        ]

    def __str__(self):
        return f"{self.key_id} ({self.status})"


# ============================================================
# Wallet Transactions
# ============================================================

class WalletTransaction(models.Model):
    """
    Immutable financial ledger entry.

    Every transaction:
    - Has a unique sequence number per wallet.
    - References the previous transaction hash.
    - Has its own SHA-256 hash.
    - Is signed using Ed25519.
    """

    class Type(models.TextChoices):
        TOPUP = "topup", "Top-up"
        PURCHASE = "purchase", "Purchase"
        REFUND = "refund", "Refund"
        ADMIN_ADJUSTMENT = "admin_adjustment", "Admin Adjustment"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="transactions",
    )

    sequence_number = models.PositiveBigIntegerField()

    type = models.CharField(
        max_length=30,
        choices=Type.choices,
    )

    # Positive = credit, negative = debit.
    amount_cents = models.BigIntegerField()

    balance_after_cents = models.BigIntegerField(
        validators=[MinValueValidator(0)],
    )

    description = models.CharField(
        max_length=255,
    )

    idempotency_key = models.CharField(
        max_length=128,
    )

    reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    # Cryptographic chain
    previous_hash = models.CharField(
        max_length=64,
        default=GENESIS_HASH,
    )

    entry_hash = models.CharField(
        max_length=64,
        unique=True,
    )

    # Version of the canonical serialization format.
    payload_version = models.PositiveSmallIntegerField(
        default=1,
    )

    # Ed25519 signature of the canonical transaction payload.
    signature = models.BinaryField()

    signing_key = models.ForeignKey(
        LedgerSigningKey,
        on_delete=models.PROTECT,
        related_name="transactions",
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
    )

    objects = ImmutableManager()

    class Meta:
        db_table = "wallet_transactions"
        verbose_name = "Wallet Transaction"
        verbose_name_plural = "Wallet Transactions"
        ordering = ["wallet", "sequence_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["wallet", "sequence_number"],
                name="wallet_unique_sequence",
            ),
            models.UniqueConstraint(
                fields=["wallet", "idempotency_key"],
                name="wallet_unique_idempotency",
            ),
            models.CheckConstraint(
                condition=Q(amount_cents__gt=0)
                | Q(amount_cents__lt=0),
                name="wallet_transaction_amount_nonzero",
            ),
            models.CheckConstraint(
                condition=Q(balance_after_cents__gte=0),
                name="wallet_transaction_balance_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        type__in=["topup", "refund"],
                        amount_cents__gt=0,
                    )
                    | Q(
                        type="purchase",
                        amount_cents__lt=0,
                    )
                    | Q(type="admin_adjustment")
                ),
                name="wallet_transaction_direction_valid",
            ),
        ]

        indexes = [
            models.Index(
                fields=["wallet", "created_at"],
                name="wallet_tx_created_idx",
            ),
            models.Index(
                fields=["type", "created_at"],
                name="wallet_tx_type_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError(
                "Wallet transactions are immutable."
            )

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError(
            "Wallet transactions cannot be deleted."
        )

    def __str__(self):
        return (
            f"{self.type}: "
            f"{self.amount_cents / 100:.2f} EUR "
            f"({self.wallet_id})"
        )


# ============================================================
# Wallet Holds
# ============================================================

class WalletHold(models.Model):
    """
    Temporary reservation of wallet funds.

    Holds reduce the available balance but do not directly
    change the actual wallet balance.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CAPTURED = "captured", "Captured"
        RELEASED = "released", "Released"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="holds",
    )

    amount_cents = models.PositiveBigIntegerField(
        validators=[MinValueValidator(1)],
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    idempotency_key = models.CharField(
        max_length=128,
    )

    reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    captured_transaction = models.OneToOneField(
        WalletTransaction,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="captured_hold",
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    objects = ImmutableManager()

    class Meta:
        db_table = "wallet_holds"
        verbose_name = "Wallet Hold"
        verbose_name_plural = "Wallet Holds"

        constraints = [
            models.UniqueConstraint(
                fields=["wallet", "idempotency_key"],
                name="wallet_hold_unique_idempotency",
            ),
            models.CheckConstraint(
                condition=Q(amount_cents__gt=0),
                name="wallet_hold_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="captured",
                        captured_transaction__isnull=False,
                    )
                    | (
                        ~Q(status="captured")
                        & Q(captured_transaction__isnull=True)
                    )
                ),
                name="wallet_hold_capture_consistent",
            ),
        ]

        indexes = [
            models.Index(
                fields=["wallet", "status"],
                name="wallet_hold_status_idx",
            ),
            models.Index(
                fields=["status", "expires_at"],
                name="wallet_hold_expiry_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.get(pk=self.pk)
            immutable_fields = (
                "wallet_id", "amount_cents", "idempotency_key",
                "reference", "expires_at", "metadata", "created_at",
            )
            if any(getattr(original, field) != getattr(self, field) for field in immutable_fields):
                raise TypeError("Wallet hold terms cannot be changed.")
            if original.status == self.status:
                if original.captured_transaction_id != self.captured_transaction_id:
                    raise TypeError("A captured transaction can only be set while capturing a hold.")
            elif original.status != self.Status.ACTIVE or self.status not in (
                self.Status.CAPTURED, self.Status.RELEASED, self.Status.EXPIRED
            ):
                raise TypeError("Invalid wallet hold state transition.")
            if self.status == self.Status.CAPTURED and not self.captured_transaction_id:
                raise TypeError("A captured hold must reference its ledger transaction.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Wallet holds cannot be deleted.")

    def __str__(self):
        return (
            f"Hold {self.amount_cents / 100:.2f} EUR "
            f"({self.status})"
        )


# ============================================================
# Global Ledger Checkpoints
# ============================================================

class LedgerCheckpoint(models.Model):
    """
    Signed snapshot of the global ledger state.

    The ledger service calculates the root hash from the
    latest transaction hash of every wallet.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    checkpoint_number = models.PositiveBigIntegerField(
        unique=True,
    )

    # Hash of the previous checkpoint.
    previous_checkpoint_hash = models.CharField(
        max_length=64,
        default=GENESIS_HASH,
    )

    # Root hash over the sorted wallet chain tips.
    ledger_root_hash = models.CharField(
        max_length=64,
    )

    checkpoint_hash = models.CharField(
        max_length=64,
        unique=True,
    )

    transaction_count = models.PositiveBigIntegerField(
        default=0,
    )

    wallet_count = models.PositiveBigIntegerField(
        default=0,
    )

    payload_version = models.PositiveSmallIntegerField(
        default=1,
    )

    signature = models.BinaryField()

    signing_key = models.ForeignKey(
        LedgerSigningKey,
        on_delete=models.PROTECT,
        related_name="checkpoints",
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
    )

    objects = ImmutableManager()

    class Meta:
        db_table = "ledger_checkpoints"
        verbose_name = "Ledger Checkpoint"
        verbose_name_plural = "Ledger Checkpoints"
        ordering = ["checkpoint_number"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError(
                "Ledger checkpoints are immutable."
            )

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError(
            "Ledger checkpoints cannot be deleted."
        )

    def __str__(self):
        return f"Checkpoint #{self.checkpoint_number}"

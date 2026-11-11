import uuid

from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion
import django.utils.timezone


GENESIS_HASH = "0" * 64


def create_existing_wallets(apps, schema_editor):
    database = schema_editor.connection.alias
    Customer = apps.get_model("customers", "Customer")
    Wallet = apps.get_model("wallet", "Wallet")
    for customer in Customer.objects.using(database).iterator():
        Wallet.objects.using(database).get_or_create(customer_id=customer.pk)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("customers", "0004_normalize_customer_preferences"),
    ]

    operations = [
        migrations.CreateModel(
            name="Wallet",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("currency", models.CharField(default="EUR", editable=False, max_length=3)),
                ("balance_cents", models.BigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="wallet", to="customers.customer")),
            ],
            options={
                "verbose_name": "Wallet",
                "verbose_name_plural": "Wallets",
                "db_table": "wallets",
            },
        ),
        migrations.CreateModel(
            name="LedgerSigningKey",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("key_id", models.CharField(max_length=64, unique=True)),
                ("label", models.CharField(max_length=100)),
                ("algorithm", models.CharField(choices=[("ed25519", "Ed25519")], default="ed25519", max_length=20)),
                ("public_key", models.BinaryField()),
                ("fingerprint", models.CharField(max_length=64, unique=True)),
                ("status", models.CharField(choices=[("active", "Active"), ("retired", "Retired"), ("revoked", "Revoked")], default="active", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("retired_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Ledger Signing Key",
                "verbose_name_plural": "Ledger Signing Keys",
                "db_table": "ledger_signing_keys",
            },
        ),
        migrations.CreateModel(
            name="WalletTransaction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sequence_number", models.PositiveBigIntegerField()),
                ("type", models.CharField(choices=[("topup", "Top-up"), ("purchase", "Purchase"), ("refund", "Refund"), ("admin_adjustment", "Admin Adjustment")], max_length=30)),
                ("amount_cents", models.BigIntegerField()),
                ("balance_after_cents", models.BigIntegerField()),
                ("description", models.CharField(max_length=255)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("reference", models.CharField(blank=True, default="", max_length=255)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("previous_hash", models.CharField(default=GENESIS_HASH, max_length=64)),
                ("entry_hash", models.CharField(max_length=64, unique=True)),
                ("payload_version", models.PositiveSmallIntegerField(default=1)),
                ("signature", models.BinaryField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("signing_key", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transactions", to="wallet.ledgersigningkey")),
                ("wallet", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transactions", to="wallet.wallet")),
            ],
            options={
                "verbose_name": "Wallet Transaction",
                "verbose_name_plural": "Wallet Transactions",
                "db_table": "wallet_transactions",
                "ordering": ["wallet", "sequence_number"],
            },
        ),
        migrations.CreateModel(
            name="WalletHold",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("amount_cents", models.PositiveBigIntegerField()),
                ("status", models.CharField(choices=[("active", "Active"), ("captured", "Captured"), ("released", "Released"), ("expired", "Expired")], default="active", max_length=20)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("reference", models.CharField(blank=True, default="", max_length=255)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("captured_transaction", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="captured_hold", to="wallet.wallettransaction")),
                ("wallet", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="holds", to="wallet.wallet")),
            ],
            options={
                "verbose_name": "Wallet Hold",
                "verbose_name_plural": "Wallet Holds",
                "db_table": "wallet_holds",
            },
        ),
        migrations.CreateModel(
            name="LedgerCheckpoint",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("checkpoint_number", models.PositiveBigIntegerField(unique=True)),
                ("previous_checkpoint_hash", models.CharField(default=GENESIS_HASH, max_length=64)),
                ("ledger_root_hash", models.CharField(max_length=64)),
                ("checkpoint_hash", models.CharField(max_length=64, unique=True)),
                ("transaction_count", models.PositiveBigIntegerField(default=0)),
                ("wallet_count", models.PositiveBigIntegerField(default=0)),
                ("payload_version", models.PositiveSmallIntegerField(default=1)),
                ("signature", models.BinaryField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("signing_key", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="checkpoints", to="wallet.ledgersigningkey")),
            ],
            options={
                "verbose_name": "Ledger Checkpoint",
                "verbose_name_plural": "Ledger Checkpoints",
                "db_table": "ledger_checkpoints",
                "ordering": ["checkpoint_number"],
            },
        ),
        migrations.AddConstraint(
            model_name="wallet",
            constraint=models.CheckConstraint(condition=Q(("balance_cents__gte", 0)), name="wallet_balance_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="wallet",
            constraint=models.CheckConstraint(condition=Q(("currency", "EUR")), name="wallet_currency_eur"),
        ),
        migrations.AddConstraint(
            model_name="ledgersigningkey",
            constraint=models.CheckConstraint(condition=Q(("algorithm", "ed25519")), name="ledger_key_algorithm_ed25519"),
        ),
        migrations.AddConstraint(
            model_name="wallettransaction",
            constraint=models.UniqueConstraint(fields=("wallet", "sequence_number"), name="wallet_unique_sequence"),
        ),
        migrations.AddConstraint(
            model_name="wallettransaction",
            constraint=models.UniqueConstraint(fields=("wallet", "idempotency_key"), name="wallet_unique_idempotency"),
        ),
        migrations.AddConstraint(
            model_name="wallettransaction",
            constraint=models.CheckConstraint(condition=Q(("amount_cents__gt", 0)) | Q(("amount_cents__lt", 0)), name="wallet_transaction_amount_nonzero"),
        ),
        migrations.AddConstraint(
            model_name="wallettransaction",
            constraint=models.CheckConstraint(condition=Q(("balance_after_cents__gte", 0)), name="wallet_transaction_balance_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="wallettransaction",
            constraint=models.CheckConstraint(
                condition=(Q(("type__in", ["topup", "refund"]), ("amount_cents__gt", 0)) | Q(("type", "purchase"), ("amount_cents__lt", 0)) | Q(("type", "admin_adjustment"))),
                name="wallet_transaction_direction_valid",
            ),
        ),
        migrations.AddIndex(
            model_name="wallettransaction",
            index=models.Index(fields=["wallet", "created_at"], name="wallet_tx_created_idx"),
        ),
        migrations.AddIndex(
            model_name="wallettransaction",
            index=models.Index(fields=["type", "created_at"], name="wallet_tx_type_idx"),
        ),
        migrations.AddIndex(
            model_name="wallettransaction",
            index=models.Index(fields=["entry_hash"], name="wallet_tx_hash_idx"),
        ),
        migrations.AddConstraint(
            model_name="wallethold",
            constraint=models.UniqueConstraint(fields=("wallet", "idempotency_key"), name="wallet_hold_unique_idempotency"),
        ),
        migrations.AddConstraint(
            model_name="wallethold",
            constraint=models.CheckConstraint(condition=Q(("amount_cents__gt", 0)), name="wallet_hold_amount_positive"),
        ),
        migrations.AddConstraint(
            model_name="wallethold",
            constraint=models.CheckConstraint(
                condition=(Q(("status", "captured"), ("captured_transaction__isnull", False)) | (~Q(("status", "captured")) & Q(("captured_transaction__isnull", True)))),
                name="wallet_hold_capture_consistent",
            ),
        ),
        migrations.AddIndex(
            model_name="wallethold",
            index=models.Index(fields=["wallet", "status"], name="wallet_hold_status_idx"),
        ),
        migrations.AddIndex(
            model_name="wallethold",
            index=models.Index(fields=["status", "expires_at"], name="wallet_hold_expiry_idx"),
        ),
        migrations.RunPython(create_existing_wallets, migrations.RunPython.noop),
    ]

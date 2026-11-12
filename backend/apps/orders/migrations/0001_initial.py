import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("customers", "0001_initial"),
        ("catalog", "0001_initial"),
        ("wallet", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(
                    choices=[
                        ("pending_payment", "Wartet auf Guthabenbuchung"),
                        ("paid", "Bezahlt"),
                        ("provisioning", "Wird bereitgestellt"),
                        ("active", "Aktiv"),
                        ("cancelled", "Storniert"),
                        ("failed", "Fehlgeschlagen"),
                    ],
                    default="pending_payment",
                    max_length=24,
                )),
                ("currency", models.CharField(default="EUR", editable=False, max_length=3)),
                ("total_cents", models.BigIntegerField(validators=[django.core.validators.MinValueValidator(0)])),
                ("idempotency_key", models.CharField(max_length=128)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="orders",
                    to="customers.customer",
                )),
                ("paid_transaction", models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="paid_order",
                    to="wallet.wallettransaction",
                )),
                ("wallet_hold", models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="order",
                    to="wallet.wallethold",
                )),
            ],
            options={
                "db_table": "orders",
                "ordering": ["-created_at"],
                "verbose_name": "Order",
                "verbose_name_plural": "Orders",
            },
        ),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("product_name", models.CharField(max_length=120)),
                ("plan_name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True, default="")),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("unit_price_cents", models.BigIntegerField(validators=[django.core.validators.MinValueValidator(0)])),
                ("setup_fee_cents", models.BigIntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)])),
                ("line_total_cents", models.BigIntegerField(validators=[django.core.validators.MinValueValidator(0)])),
                ("billing_interval_unit", models.CharField(max_length=10)),
                ("billing_interval_count", models.PositiveSmallIntegerField(default=1)),
                ("resource_limits", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("order", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="items",
                    to="orders.order",
                )),
                ("plan", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="order_items",
                    to="catalog.hostingplan",
                )),
            ],
            options={
                "db_table": "order_items",
                "verbose_name": "Order item",
                "verbose_name_plural": "Order items",
            },
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.UniqueConstraint(
                fields=("customer", "idempotency_key"),
                name="order_customer_idempotency_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=Q(total_cents__gte=0),
                name="order_total_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=Q(currency="EUR"),
                name="order_currency_eur",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=(Q(status="paid", paid_at__isnull=False) | ~Q(status="paid")),
                name="order_paid_requires_timestamp",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=(
                    Q(status="paid", total_cents=0, paid_transaction__isnull=True)
                    | Q(status="paid", total_cents__gt=0, paid_transaction__isnull=False)
                    | ~Q(status="paid")
                ),
                name="order_paid_payment_consistent",
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["customer", "status", "created_at"], name="order_customer_status_idx"),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="order_item_quantity_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=Q(unit_price_cents__gte=0),
                name="order_item_unit_price_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=Q(setup_fee_cents__gte=0),
                name="order_item_setup_fee_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=Q(line_total_cents__gte=0),
                name="order_item_total_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=Q(billing_interval_count__gte=1),
                name="order_item_interval_positive",
            ),
        ),
    ]

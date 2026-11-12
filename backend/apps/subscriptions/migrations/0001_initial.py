import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("customers", "0001_initial"),
        ("orders", "0001_initial"),
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(
                    choices=[
                        ("active", "Aktiv"),
                        ("past_due", "Guthaben ausstehend"),
                        ("suspended", "Pausiert"),
                        ("cancelled", "Gekündigt"),
                        ("expired", "Abgelaufen"),
                    ],
                    default="active",
                    max_length=16,
                )),
                ("currency", models.CharField(default="EUR", editable=False, max_length=3)),
                ("price_cents", models.BigIntegerField(validators=[django.core.validators.MinValueValidator(0)])),
                ("billing_interval_unit", models.CharField(
                    choices=[
                        ("day", "Tag(e)"),
                        ("week", "Woche(n)"),
                        ("month", "Monat(e)"),
                        ("year", "Jahr(e)"),
                    ],
                    max_length=10,
                )),
                ("billing_interval_count", models.PositiveSmallIntegerField(default=1)),
                ("current_period_start", models.DateTimeField()),
                ("current_period_end", models.DateTimeField()),
                ("next_billing_at", models.DateTimeField()),
                ("auto_renew", models.BooleanField(default=False)),
                ("cancel_at_period_end", models.BooleanField(default=False)),
                ("past_due_since", models.DateTimeField(blank=True, null=True)),
                ("last_renewal_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("last_renewed_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="subscriptions",
                    to="customers.customer",
                )),
                ("order_item", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="subscription",
                    to="orders.orderitem",
                )),
                ("plan", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="subscriptions",
                    to="catalog.hostingplan",
                )),
            ],
            options={
                "db_table": "subscriptions",
                "ordering": ["-created_at"],
                "verbose_name": "Subscription",
                "verbose_name_plural": "Subscriptions",
            },
        ),
        migrations.AddConstraint(
            model_name="subscription",
            constraint=models.CheckConstraint(
                condition=Q(currency="EUR"),
                name="subscription_currency_eur",
            ),
        ),
        migrations.AddConstraint(
            model_name="subscription",
            constraint=models.CheckConstraint(
                condition=Q(price_cents__gte=0),
                name="subscription_price_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="subscription",
            constraint=models.CheckConstraint(
                condition=Q(billing_interval_count__gte=1),
                name="subscription_interval_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="subscription",
            constraint=models.CheckConstraint(
                condition=Q(current_period_end__gt=F("current_period_start")),
                name="subscription_period_order_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="subscription",
            constraint=models.CheckConstraint(
                condition=Q(status="cancelled", cancelled_at__isnull=False) | ~Q(status="cancelled"),
                name="subscription_cancel_requires_timestamp",
            ),
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(fields=["status", "next_billing_at"], name="subscription_due_idx"),
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(fields=["customer", "status"], name="subscription_customer_status_idx"),
        ),
    ]

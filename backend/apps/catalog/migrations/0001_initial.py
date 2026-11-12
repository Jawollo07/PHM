import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="HostingProduct",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(max_length=140, unique=True)),
                ("description", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=False)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "catalog_hosting_products",
                "ordering": ["sort_order", "name"],
                "verbose_name": "Hosting product",
                "verbose_name_plural": "Hosting products",
            },
        ),
        migrations.CreateModel(
            name="HostingPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(max_length=140)),
                ("description", models.TextField(blank=True, default="")),
                ("price_cents", models.BigIntegerField(validators=[django.core.validators.MinValueValidator(0)])),
                ("setup_fee_cents", models.BigIntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)])),
                ("billing_interval_unit", models.CharField(
                    choices=[
                        ("once", "Einmalig"),
                        ("day", "Tag(e)"),
                        ("week", "Woche(n)"),
                        ("month", "Monat(e)"),
                        ("year", "Jahr(e)"),
                    ],
                    default="month",
                    max_length=10,
                )),
                ("billing_interval_count", models.PositiveSmallIntegerField(default=1)),
                ("resource_limits", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=False)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("product", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="plans",
                    to="catalog.hostingproduct",
                )),
            ],
            options={
                "db_table": "catalog_hosting_plans",
                "ordering": ["product__sort_order", "sort_order", "name"],
                "verbose_name": "Hosting plan",
                "verbose_name_plural": "Hosting plans",
            },
        ),
        migrations.AddConstraint(
            model_name="hostingplan",
            constraint=models.UniqueConstraint(
                fields=("product", "slug"),
                name="catalog_plan_product_slug_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="hostingplan",
            constraint=models.CheckConstraint(
                condition=Q(price_cents__gte=0),
                name="catalog_plan_price_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="hostingplan",
            constraint=models.CheckConstraint(
                condition=Q(setup_fee_cents__gte=0),
                name="catalog_plan_setup_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="hostingplan",
            constraint=models.CheckConstraint(
                condition=Q(billing_interval_count__gte=1),
                name="catalog_plan_interval_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="hostingplan",
            constraint=models.CheckConstraint(
                condition=(
                    Q(billing_interval_unit="once", billing_interval_count=1)
                    | ~Q(billing_interval_unit="once")
                ),
                name="catalog_plan_once_interval_one",
            ),
        ),
        migrations.AddConstraint(
            model_name="hostingplan",
            constraint=models.CheckConstraint(
                condition=Q(billing_interval_unit__in=["once", "day", "week", "month", "year"]),
                name="catalog_plan_interval_unit_valid",
            ),
        ),
        migrations.AddIndex(
            model_name="hostingproduct",
            index=models.Index(fields=["is_active", "sort_order"], name="catalog_product_active_idx"),
        ),
        migrations.AddIndex(
            model_name="hostingplan",
            index=models.Index(fields=["product", "is_active", "sort_order"], name="catalog_plan_active_idx"),
        ),
    ]

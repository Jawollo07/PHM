import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0001_initial"),
        ("orders", "0001_initial"),
        ("pelican", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PelicanServer",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("quantity_index", models.PositiveIntegerField(default=1)),
                ("external_id", models.CharField(editable=False, max_length=255, unique=True)),
                ("panel_server_id", models.PositiveBigIntegerField(blank=True, null=True, unique=True)),
                ("panel_uuid", models.CharField(blank=True, default="", max_length=64)),
                ("panel_identifier", models.CharField(blank=True, default="", max_length=32)),
                ("panel_name", models.CharField(blank=True, default="", max_length=255)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("provisioning", "Provisioning"), ("installing", "Installing"), ("installed", "Installed"), ("failed", "Failed")], default="pending", max_length=16)),
                ("last_error_code", models.CharField(blank=True, default="", max_length=64)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("next_retry_at", models.DateTimeField(blank=True, null=True)),
                ("provisioned_at", models.DateTimeField(blank=True, null=True)),
                ("installed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pelican_servers", to="customers.customer")),
                ("order_item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pelican_servers", to="orders.orderitem")),
            ],
            options={"db_table": "pelican_servers", "ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="pelicanserver",
            constraint=models.UniqueConstraint(fields=("order_item", "quantity_index"), name="pelican_item_unit_unique"),
        ),
        migrations.AddConstraint(
            model_name="pelicanserver",
            constraint=models.CheckConstraint(condition=models.Q(("quantity_index__gte", 1)), name="pelican_unit_index_positive"),
        ),
        migrations.AddConstraint(
            model_name="pelicanserver",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ["installing", "installed"]), ("panel_server_id__isnull", False))
                | ~models.Q(("status__in", ["installing", "installed"])),
                name="pelican_server_remote_id_required",
            ),
        ),
        migrations.AddIndex(
            model_name="pelicanserver",
            index=models.Index(fields=["status", "last_attempt_at", "created_at"], name="pelican_server_queue_idx"),
        ),
        migrations.AddIndex(
            model_name="pelicanserver",
            index=models.Index(fields=["customer", "status"], name="pelican_customer_status_idx"),
        ),
    ]

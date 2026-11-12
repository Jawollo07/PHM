from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("customers", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="PelicanAccount",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("panel_user_id", models.PositiveBigIntegerField(blank=True, null=True, unique=True)),
                ("panel_email", models.EmailField(blank=True, default="", max_length=254)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("linked", "Linked"), ("failed", "Failed")], default="pending", max_length=12)),
                ("last_error_code", models.CharField(blank=True, default="", max_length=64)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("linked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="pelican_account", to="customers.customer")),
            ],
            options={"db_table": "pelican_accounts", "ordering": ["created_at"]},
        ),
        migrations.AddConstraint(
            model_name="pelicanaccount",
            constraint=models.CheckConstraint(
                condition=models.Q(("status", "linked"), ("panel_user_id__isnull", False)) | ~models.Q(("status", "linked")),
                name="pelican_linked_requires_panel_id",
            ),
        ),
    ]

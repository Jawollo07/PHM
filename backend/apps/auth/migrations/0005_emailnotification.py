# Generated for durable outbound email notifications.
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0004_alter_user_is_staff"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailNotification",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("category", models.CharField(choices=[("payment", "Payment"), ("service", "Service"), ("security", "Security")], max_length=20)),
                ("recipient", models.EmailField(max_length=254)),
                ("subject", models.CharField(max_length=255)),
                ("message", models.TextField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("processing", "Processing"), ("sent", "Sent"), ("failed", "Failed")], db_index=True, default="pending", max_length=20)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("max_attempts", models.PositiveSmallIntegerField(default=8)),
                ("available_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="email_notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "accounts_email_notification", "ordering": ["created_at"]},
        ),
        migrations.AddIndex(
            model_name="emailnotification",
            index=models.Index(fields=["status", "available_at"], name="email_notif_due_idx"),
        ),
    ]

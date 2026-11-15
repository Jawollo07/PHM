from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0002_subscription_integrity_triggers"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="subscription",
            old_name="subscription_customer_status",
            new_name="sub_customer_status_idx",
        ),
    ]

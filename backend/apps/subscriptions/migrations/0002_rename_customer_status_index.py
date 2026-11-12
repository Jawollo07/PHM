from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="subscription",
            old_name="subscription_customer_status_idx",
            new_name="sub_customer_status_idx",
        ),
    ]

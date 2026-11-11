from django.db import migrations


def migrate_customer_data(apps, schema_editor):
    database = schema_editor.connection.alias
    User = apps.get_model("accounts", "User")
    UserProfile = apps.get_model("accounts", "UserProfile")
    Customer = apps.get_model("customers", "Customer")
    CustomerSettings = apps.get_model("customers", "CustomerSettings")

    for user in User.objects.using(database).iterator():
        customer, _ = Customer.objects.using(database).get_or_create(user_id=user.pk)
        settings, _ = CustomerSettings.objects.using(database).get_or_create(
            customer_id=customer.pk
        )
        profile, created = UserProfile.objects.using(database).get_or_create(
            user_id=user.pk,
            defaults={"language": getattr(settings, "language", "de")},
        )
        if not created and getattr(settings, "language", "de") != "de":
            profile.language = settings.language
            profile.save(using=database, update_fields=["language"])


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0003_remove_customersettings_timezone"),
        ("accounts", "0004_alter_user_is_staff"),
    ]

    operations = [
        migrations.RunPython(migrate_customer_data, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="customersettings",
            name="language",
        ),
    ]

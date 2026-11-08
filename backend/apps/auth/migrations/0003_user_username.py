from django.db import migrations, models
from django.utils.text import slugify


def populate_usernames(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    database = schema_editor.connection.alias
    used_usernames = set()

    for user in User.objects.using(database).order_by("pk").iterator():
        base = slugify(user.email.partition("@")[0], allow_unicode=True)[:150]
        base = base or f"user-{user.pk}"
        username = base
        suffix = 2

        while username in used_usernames:
            suffix_text = f"-{suffix}"
            username = f"{base[:150 - len(suffix_text)]}{suffix_text}"
            suffix += 1

        user.username = username
        user.save(using=database, update_fields=["username"])
        used_usernames.add(username)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_remove_user_roles_alter_user_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="username",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=150,
                null=True,
            ),
        ),
        migrations.RunPython(populate_usernames, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="username",
            field=models.CharField(
                db_index=True,
                max_length=150,
                unique=True,
            ),
        ),
    ]

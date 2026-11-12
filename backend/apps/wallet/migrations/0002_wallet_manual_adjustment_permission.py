from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("wallet", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="wallet",
            options={
                "verbose_name": "Wallet",
                "verbose_name_plural": "Wallets",
                "db_table": "wallets",
                "permissions": [
                    ("adjust_wallet_balance", "Can manually adjust customer wallet balances"),
                ],
            },
        ),
    ]

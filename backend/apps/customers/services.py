from django.conf import settings
from django.db import transaction

from apps.auth.models import UserProfile
from apps.customers.models import Customer, CustomerSettings
from apps.wallet.models import Wallet
from apps.wallet.services import (
    create_configured_ledger_checkpoint,
    lock_ledger_signing_keys,
)


def provision_personal_customer(user, using=None):
    """Atomically ensure a user's personal customer, profile, settings and wallet exist."""
    with transaction.atomic(using=using):
        customers = Customer.objects.db_manager(using)
        profiles = UserProfile.objects.db_manager(using)
        customer_settings = CustomerSettings.objects.db_manager(using)
        wallets = Wallet.objects.db_manager(using)

        customer, _ = customers.get_or_create(user=user)
        profiles.get_or_create(user=user)
        customer_settings.get_or_create(customer=customer)
        lock_ledger_signing_keys(using=using)
        _, wallet_created = wallets.get_or_create(customer=customer)
        if wallet_created and settings.WALLET_LEDGER_AUTO_CHECKPOINT:
            create_configured_ledger_checkpoint(using=using)
        return customer

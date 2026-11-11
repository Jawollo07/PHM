from django.db import transaction

from apps.auth.models import UserProfile
from apps.customers.models import Customer, CustomerSettings
from apps.wallet.models import Wallet


def provision_personal_customer(user, using=None):
    """Atomically ensure a user's personal customer, profile, settings and wallet exist."""
    with transaction.atomic(using=using):
        customers = Customer.objects.db_manager(using)
        profiles = UserProfile.objects.db_manager(using)
        settings = CustomerSettings.objects.db_manager(using)
        wallets = Wallet.objects.db_manager(using)

        customer, _ = customers.get_or_create(user=user)
        profiles.get_or_create(user=user)
        settings.get_or_create(customer=customer)
        wallets.get_or_create(customer=customer)
        return customer

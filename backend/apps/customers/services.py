from django.db import transaction

from apps.auth.models import UserProfile
from apps.customers.models import Customer, CustomerSettings
from apps.wallet.models import Wallet


@transaction.atomic
def provision_personal_customer(user):
    """Ensure a user's personal customer, preferences, profile and wallet exist."""
    customer, _ = Customer.objects.get_or_create(user=user)
    UserProfile.objects.get_or_create(user=user)
    CustomerSettings.objects.get_or_create(customer=customer)
    Wallet.objects.get_or_create(customer=customer)
    return customer

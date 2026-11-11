import pycountry

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from apps.auth.models import UserProfile
from apps.customers.forms import AccountDetailsForm
from apps.customers.models import Customer, CustomerAddress, CustomerSettings
from apps.customers.services import provision_personal_customer


def get_customer_details(user):
    try:
        customer = user.customer
    except Customer.DoesNotExist:
        return None
    return {"phone_number": customer.phone_number}


def get_customer_address(user):
    try:
        customer = user.customer
    except Customer.DoesNotExist:
        return None

    address = (
        customer.addresses.filter(address_type=CustomerAddress.Type.CONTACT).first()
        or customer.addresses.filter(address_type=CustomerAddress.Type.BILLING).first()
    )
    if not address:
        return None

    address_type = {
        CustomerAddress.Type.BILLING: "Rechnungsadresse",
        CustomerAddress.Type.CONTACT: "Kontaktadresse",
    }.get(address.address_type, "Adresse")
    return {
        "address_type": address_type,
        "recipient_name": address.recipient_name,
        "company_name": address.company_name,
        "address_line_2": address.address_line_2,
        "house_number": address.house_number,
        "street": address.street,
        "postal_code": address.postal_code,
        "city": address.city,
        "state": address.state,
        "country": address.country,
    }


def get_customer_settings(user):
    try:
        customer = user.customer
        customer_settings = customer.settings
    except (Customer.DoesNotExist, CustomerSettings.DoesNotExist):
        return None

    try:
        profile = user.profile
        language_code = profile.language
    except UserProfile.DoesNotExist:
        language_code = "de"

    language = pycountry.languages.get(alpha_2=language_code)
    return {
        "language": language.name if language else language_code,
        "notification_settings": {
            "email_notifications": customer_settings.email_notifications,
            "service_notifications": customer_settings.service_notifications,
            "payment_notifications": customer_settings.payment_notifications,
            "security_notifications": customer_settings.security_notifications,
            "marketing_emails": customer_settings.marketing_emails,
        },
    }


def _save_account_details(user, form):
    data = form.cleaned_data
    user.username = data["username"]
    user.email = data["email"]
    user.save(update_fields=["username", "email"])

    customer = provision_personal_customer(user)
    customer.phone_number = data["phone_number"]
    customer.save(update_fields=["phone_number", "updated_at"])

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.language = data["language"]
    profile.save(update_fields=["language", "updated_at"])

    address = customer.addresses.filter(
        address_type=CustomerAddress.Type.CONTACT
    ).first()
    has_address_details = any(data[field] for field in AccountDetailsForm.address_fields)
    if address or has_address_details:
        if address is None:
            address = CustomerAddress(
                customer=customer,
                address_type=CustomerAddress.Type.CONTACT,
            )
        for field in AccountDetailsForm.address_fields:
            setattr(address, field, data[field])
        address.country = data["country"] or "Germany"
        address.save()

    customer_settings = customer.settings
    for field in (
        "email_notifications",
        "service_notifications",
        "payment_notifications",
        "security_notifications",
        "marketing_emails",
    ):
        setattr(customer_settings, field, data[field])
    customer_settings.save()


@login_required(login_url="auth")
def account_view(request):
    user = request.user
    try:
        customer = user.customer
    except Customer.DoesNotExist:
        customer = None

    address = None
    customer_settings = None
    if customer:
        address = (
            customer.addresses.filter(address_type=CustomerAddress.Type.CONTACT).first()
            or customer.addresses.filter(address_type=CustomerAddress.Type.BILLING).first()
        )
        try:
            customer_settings = customer.settings
        except CustomerSettings.DoesNotExist:
            pass

    form = AccountDetailsForm(
        request.POST if request.method == "POST" else None,
        user=user,
        customer=customer,
        address=address,
        customer_settings=customer_settings,
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            _save_account_details(user, form)
        messages.success(request, "Deine Kontodaten wurden gespeichert.")
        return redirect("account")

    customer_settings_details = get_customer_settings(user)
    return render(
        request,
        "customers/index.html",
        {
            "user_details": {"username": user.username, "email": user.email},
            "customer_details": get_customer_details(user),
            "customer_address": get_customer_address(user),
            "customer_settings": customer_settings_details,
            "customer_notification_settings": (
                customer_settings_details.get("notification_settings")
                if customer_settings_details else None
            ),
            "form": form,
        },
    )

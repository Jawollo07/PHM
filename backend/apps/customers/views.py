from decimal import Decimal

import pycountry
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from apps.auth.models import EmailVerification, UserProfile
from apps.auth.services import issue_email_verification
from apps.customers.forms import AccountDetailsForm
from apps.customers.models import Customer, CustomerAddress, CustomerSettings
from apps.customers.services import provision_personal_customer
from apps.orders.models import Order
from apps.pelican.models import PelicanServer
from apps.pelican.presentation import server_resource_details, server_status_label
from apps.subscriptions.models import Subscription
from apps.wallet.models import Wallet, WalletTransaction


def _format_eur(cents):
    amount = f"{Decimal(cents) / Decimal('100'):,.2f}"
    return f"{amount.replace(',', 'X').replace('.', ',').replace('X', '.')} EUR"


def get_wallet_details(user):
    try:
        wallet = user.customer.wallet
    except (Customer.DoesNotExist, Wallet.DoesNotExist):
        return None

    return {
        "balance": _format_eur(wallet.balance_cents),
        "available_balance": _format_eur(wallet.available_balance_cents),
        "reserved_balance": _format_eur(wallet.reserved_balance_cents),
        "transactions": [
            {
                "description": entry.description,
                "date": entry.created_at,
                "type": entry.get_type_display(),
                "reference": entry.reference,
                "amount": _format_eur(entry.amount_cents),
                "balance_after": _format_eur(entry.balance_after_cents),
            }
            for entry in wallet.transactions.order_by("-sequence_number")[:10]
        ],
    }


def get_customer_overview(customer):
    if customer is None:
        return {
            "orders": [],
            "order_count": 0,
            "subscriptions": [],
            "subscription_count": 0,
            "servers": [],
            "server_count": 0,
            "billing_entries": [],
        }

    orders = Order.objects.filter(customer=customer)
    subscriptions = Subscription.objects.filter(customer=customer)
    servers = list(
        PelicanServer.objects.filter(customer=customer)
        .select_related("order_item", "order_item__order")
        .order_by("-created_at")[:4]
    )
    for server in servers:
        server.resource_details = server_resource_details(
            server.order_item.resource_limits
        )
        server.customer_status_display = server_status_label(server.status)

    wallet = Wallet.objects.filter(customer=customer).first()
    billing_entries = []
    if wallet is not None:
        billing_entries = [
            {
                "date": entry.created_at,
                "description": entry.description,
                "reference": entry.reference,
                "amount": _format_eur(abs(entry.amount_cents)),
                "kind": (
                    "Aboverlängerung"
                    if entry.metadata.get("source") == "subscription_renewal"
                    else "Bestellung"
                ),
            }
            for entry in wallet.transactions.filter(
                type=WalletTransaction.Type.PURCHASE
            ).order_by("-sequence_number")[:5]
        ]

    return {
        "orders": list(
            orders.prefetch_related("items").order_by("-created_at")[:4]
        ),
        "order_count": orders.count(),
        "subscriptions": list(
            subscriptions.select_related("plan", "order_item")
            .order_by("-created_at")[:4]
        ),
        "subscription_count": subscriptions.count(),
        "servers": servers,
        "server_count": PelicanServer.objects.filter(customer=customer).count(),
        "billing_entries": billing_entries,
    }


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
    email_changed = user.email.lower() != data["email"].lower()
    user.username = data["username"]
    user.email = data["email"]
    update_fields = ["username", "email", "updated_at"]
    if email_changed:
        user.email_verified = False
        user.email_verified_at = None
        update_fields.extend(["email_verified", "email_verified_at"])
    user.save(update_fields=update_fields)

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
                is_default=True,
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
    return email_changed


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
            email_changed = _save_account_details(user, form)
            if email_changed:
                issue_email_verification(
                    user,
                    request=request,
                    purpose=EmailVerification.Purpose.EMAIL_CHANGE,
                )
        messages.success(request, "Deine Kontodaten wurden gespeichert.")
        if email_changed:
            messages.info(
                request,
                "Deine E-Mail-Adresse ist noch nicht bestätigt. "
                "Wir haben dir einen neuen Bestätigungslink gesendet.",
            )
        return redirect("account")

    customer_settings_details = get_customer_settings(user)
    return render(
        request,
        "customers/index.html",
        {
            "user_details": {
                "username": user.username,
                "email": user.email,
                "email_verified": user.email_verified,
            },
            "customer_details": get_customer_details(user),
            "wallet_details": get_wallet_details(user),
            "customer_address": get_customer_address(user),
            "customer_settings": customer_settings_details,
            "customer_overview": get_customer_overview(customer),
            "customer_notification_settings": (
                customer_settings_details.get("notification_settings")
                if customer_settings_details else None
            ),
            "form": form,
        },
    )

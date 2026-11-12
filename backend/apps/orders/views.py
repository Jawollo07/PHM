import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Prefetch
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string

from apps.catalog.models import HostingPlan, HostingProduct
from apps.wallet.models import LedgerSigningKey
from apps.wallet.services import InsufficientFunds

from .models import Order
from .services import (
    IdempotencyConflict,
    OrderError,
    OrderNotPayable,
    purchase_plan,
)


def _eur(cents):
    return Decimal(cents) / Decimal("100")


@login_required(login_url="auth")
def catalog_view(request):
    plans = HostingPlan.objects.filter(is_active=True).select_related("product").order_by(
        "product__sort_order", "sort_order", "name"
    )
    products = (
        HostingProduct.objects.filter(is_active=True, plans__is_active=True)
        .distinct()
        .order_by("sort_order", "name")
        .prefetch_related(Prefetch("plans", queryset=plans, to_attr="available_plans"))
    )
    wallet = request.user.customer.wallet
    return render(
        request,
        "orders/catalog.html",
        {
            "products": products,
            "wallet_balance": _eur(wallet.balance_cents),
            "wallet_available": _eur(wallet.available_balance_cents),
            "new_idempotency_key": uuid.uuid4(),
        },
    )


@login_required(login_url="auth")
def purchase_plan_view(request, plan_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        idempotency_key = str(uuid.UUID(request.POST.get("idempotency_key", "")))
    except (ValueError, TypeError, AttributeError):
        messages.error(request, "Die Bestellanfrage ist ungültig. Bitte lade die Seite neu.")
        return redirect("catalog")

    signing_key = None
    signer = None
    key_id = getattr(settings, "WALLET_LEDGER_KEY_ID", "")
    signer_path = getattr(settings, "WALLET_LEDGER_SIGNER", "")
    if key_id and signer_path:
        try:
            signing_key = LedgerSigningKey.objects.get(
                key_id=key_id,
                status=LedgerSigningKey.Status.ACTIVE,
            )
            signer = import_string(signer_path)
        except (LedgerSigningKey.DoesNotExist, LedgerSigningKey.MultipleObjectsReturned):
            signing_key = None
            signer = None
        except (ImproperlyConfigured, ImportError, AttributeError):
            signing_key = None
            signer = None

    try:
        order = purchase_plan(
            request.user.customer_id,
            plan_id,
            idempotency_key=idempotency_key,
            signing_key_id=signing_key.pk if signing_key else None,
            signer=signer,
        )
    except HostingPlan.DoesNotExist:
        messages.error(request, "Dieser Tarif ist nicht verfügbar.")
        return redirect("catalog")
    except IdempotencyConflict:
        messages.error(request, "Diese Bestellkennung wurde bereits für eine andere Bestellung verwendet.")
        return redirect("catalog")
    except InsufficientFunds:
        messages.error(request, "Dein verfügbares Guthaben reicht für diesen Tarif nicht aus. Bitte wende dich an den Support, wenn eine manuelle Gutschrift benötigt wird.")
        return redirect("catalog")
    except OrderNotPayable as exc:
        messages.error(request, str(exc))
        return redirect("catalog")
    except OrderError as exc:
        messages.error(request, str(exc))
        return redirect("catalog")
    except Exception as exc:
        # Do not expose database, signing, or internal service details to customers.
        messages.error(request, "Die Bestellung konnte nicht sicher abgeschlossen werden. Bitte wende dich an den Support.")
        return redirect("catalog")

    if order.status == Order.Status.PAID:
        messages.success(request, f"Bestellung {order.pk} wurde erfolgreich angelegt.")
    else:
        messages.error(request, "Die Bestellung wurde nicht bezahlt und nicht bereitgestellt.")
    return redirect("orders")


@login_required(login_url="auth")
def orders_view(request):
    orders = (
        Order.objects.filter(customer=request.user.customer)
        .prefetch_related("items")
        .select_related("wallet_hold", "paid_transaction")
        .order_by("-created_at")
    )
    return render(request, "orders/list.html", {"orders": orders})


@login_required(login_url="auth")
def order_detail_view(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related("items").select_related(
            "wallet_hold", "paid_transaction"
        ),
        pk=order_id,
        customer=request.user.customer,
    )
    return render(request, "orders/detail.html", {"order": order})

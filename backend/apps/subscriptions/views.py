from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Subscription
from .services import (
    SubscriptionError,
    cancel_subscription,
    set_auto_renew,
)


@login_required(login_url="auth")
def subscriptions_view(request):
    subscriptions = (
        Subscription.objects.filter(customer=request.user.customer)
        .select_related("plan", "order_item")
        .order_by("-created_at")
    )
    return render(
        request,
        "subscriptions/list.html",
        {"subscriptions": subscriptions},
    )


@login_required(login_url="auth")
@require_POST
def subscription_action_view(request, subscription_id):
    action = request.POST.get("action", "")
    try:
        if action == "enable_auto_renew":
            set_auto_renew(subscription_id, request.user.customer.pk, True)
            messages.success(request, "Die automatische Verlängerung wurde aktiviert.")
        elif action == "disable_auto_renew":
            set_auto_renew(subscription_id, request.user.customer.pk, False)
            messages.success(
                request,
                "Die automatische Verlängerung ist deaktiviert. "
                "Der aktuelle Zeitraum bleibt bestehen.",
            )
        elif action == "cancel_at_period_end":
            cancel_subscription(
                subscription_id,
                request.user.customer.pk,
                at_period_end=True,
            )
            messages.success(
                request,
                "Die Kündigung zum Ende des bereits bezahlten Zeitraums wurde vorgemerkt.",
            )
        else:
            messages.error(request, "Die angeforderte Aktion ist ungültig.")
    except Subscription.DoesNotExist:
        messages.error(request, "Dieses Abonnement wurde nicht gefunden.")
    except SubscriptionError as exc:
        messages.error(request, str(exc))
    return redirect("subscriptions")

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.customers.models import Customer
from .models import PelicanServer


@login_required(login_url="auth")
def servers_view(request):
    customer = Customer.objects.filter(user=request.user).first()
    servers = []
    if customer is not None:
        servers = list(
            PelicanServer.objects.filter(customer=customer)
            .select_related("order_item", "order_item__order")
            .order_by("-created_at")
        )

    panel_url = getattr(settings, "PELICAN_PANEL_URL", "").rstrip("/")
    if not panel_url.startswith("https://"):
        panel_url = ""

    for server in servers:
        server.panel_url = (
            f"{panel_url}/server/{server.panel_uuid}"
            if panel_url and server.panel_uuid and server.status == PelicanServer.Status.INSTALLED
            else ""
        )

    return render(request, "pelican/servers.html", {"servers": servers})

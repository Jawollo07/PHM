from django.contrib.auth import logout
from django.shortcuts import redirect

from apps.customers.models import Customer


class ActiveCustomerMiddleware:
    """End authenticated customer sessions when the personal account is suspended."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.path.startswith("/admin/"):
            try:
                customer = request.user.customer
            except Customer.DoesNotExist:
                customer = None

            if customer is not None and not customer.is_active:
                logout(request)
                if not request.path.startswith("/auth/"):
                    return redirect("auth")

        return self.get_response(request)

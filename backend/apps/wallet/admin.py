import uuid
from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.helpers import AdminForm
from django.contrib.admin.utils import quote
from django.core.exceptions import PermissionDenied, ImproperlyConfigured
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.module_loading import import_string

from .models import LedgerCheckpoint, LedgerSigningKey, Wallet, WalletHold, WalletTransaction
from .services import InsufficientFunds, InvalidLedgerOperation, credit_wallet, debit_wallet


class ManualWalletAdjustmentForm(forms.Form):
    wallet = forms.ModelChoiceField(
        queryset=Wallet.objects.select_related("customer__user").order_by("customer__user__username"),
        label="Kundenkonto",
    )
    direction = forms.ChoiceField(
        choices=(("credit", "Gutschrift"), ("debit", "Belastung")),
        label="Art der Buchung",
    )
    amount_eur = forms.DecimalField(
        label="Betrag in EUR",
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        help_text="Beträge werden exakt in Euro-Cent verbucht.",
    )
    reason = forms.CharField(
        label="Begründung",
        max_length=255,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    reference = forms.CharField(
        label="Interne Referenz (optional)",
        max_length=255,
        required=False,
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["idempotency_key"].initial = uuid.uuid4()

    def clean_amount_eur(self):
        amount = self.cleaned_data["amount_eur"]
        cents = amount * 100
        if cents != cents.to_integral_value():
            raise forms.ValidationError("Der Betrag muss auf volle Cent lauten.")
        return int(cents)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    change_list_template = "admin/wallet/wallet/change_list.html"
    list_display = ("id", "customer", "currency", "balance_cents", "created_at", "manual_adjustment_link")
    search_fields = ("id", "customer__user__username", "customer__user__email")
    readonly_fields = tuple(field.name for field in Wallet._meta.fields)

    def get_urls(self):
        custom_urls = [
            path(
                "manual-adjustment/",
                self.admin_site.admin_view(self.manual_adjustment_view),
                name="wallet_manual_adjustment",
            ),
        ]
        return custom_urls + super().get_urls()

    @admin.display(description="Guthaben verwalten")
    def manual_adjustment_link(self, obj):
        if not obj:
            return "—"
        url = reverse("admin:wallet_manual_adjustment")
        return format_html('<a class="button" href="{}?wallet={}">Guthaben ändern</a>', url, obj.pk)

    def manual_adjustment_view(self, request):
        if not request.user.has_perm("wallet.adjust_wallet_balance"):
            raise PermissionDenied

        initial = {}
        wallet_id = request.GET.get("wallet")
        if wallet_id:
            initial["wallet"] = wallet_id
        form = ManualWalletAdjustmentForm(request.POST or None, initial=initial)

        if request.method == "POST" and form.is_valid():
            try:
                signer_path = getattr(settings, "WALLET_LEDGER_SIGNER", "")
                if not signer_path:
                    raise ImproperlyConfigured(
                        "WALLET_LEDGER_SIGNER ist nicht konfiguriert. "
                        "Manuelle Buchungen bleiben bis zur Einrichtung des externen Signaturdienstes deaktiviert."
                    )
                signer = import_string(signer_path)
                signing_key = LedgerSigningKey.objects.get(status=LedgerSigningKey.Status.ACTIVE)
                amount_cents = form.cleaned_data["amount_eur"]
                metadata = {
                    "source": "django_admin_manual_adjustment",
                    "admin_user_id": str(request.user.pk),
                    "admin_username": request.user.get_username(),
                }
                common = {
                    "description": form.cleaned_data["reason"].strip(),
                    "idempotency_key": str(form.cleaned_data["idempotency_key"]),
                    "signing_key_id": signing_key.pk,
                    "signer": signer,
                    "reference": form.cleaned_data["reference"].strip(),
                    "metadata": metadata,
                }
                if not common["description"]:
                    form.add_error("reason", "Eine Begründung ist erforderlich.")
                else:
                    if form.cleaned_data["direction"] == "credit":
                        entry = credit_wallet(
                            form.cleaned_data["wallet"].pk,
                            amount_cents,
                            transaction_type=WalletTransaction.Type.ADMIN_ADJUSTMENT,
                            **common,
                        )
                    else:
                        entry = debit_wallet(
                            form.cleaned_data["wallet"].pk,
                            amount_cents,
                            **common,
                        )
                    messages.success(
                        request,
                        f"Buchung #{entry.sequence_number} gespeichert. "
                        f"Neuer Kontostand: {entry.balance_after_cents / 100:.2f} EUR.",
                    )
                    return HttpResponseRedirect(reverse("admin:wallet_wallet_changelist"))
            except (LedgerSigningKey.DoesNotExist, LedgerSigningKey.MultipleObjectsReturned):
                form.add_error(None, "Es muss genau ein aktiver Ledger-Signaturschlüssel vorhanden sein.")
            except (InsufficientFunds, InvalidLedgerOperation) as exc:
                form.add_error(None, str(exc))
            except ImproperlyConfigured as exc:
                form.add_error(None, str(exc))

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Manuelle Guthabenbuchung",
            "form": form,
            "has_view_permission": self.has_view_permission(request),
            "has_permission": True,
        }
        return render(request, "admin/wallet/wallet/manual_adjustment.html", context)

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WalletHold)
class WalletHoldAdmin(admin.ModelAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    list_display = ("id", "wallet", "amount_cents", "status", "expires_at")
    list_filter = ("status",)
    readonly_fields = tuple(field.name for field in WalletHold._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    list_display = ("wallet", "sequence_number", "type", "amount_cents", "created_at")
    list_filter = ("type",)
    search_fields = ("entry_hash", "idempotency_key", "reference")
    readonly_fields = tuple(field.name for field in WalletTransaction._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerSigningKey)
class LedgerSigningKeyAdmin(admin.ModelAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    list_display = ("key_id", "label", "algorithm", "status", "created_at")
    list_filter = ("algorithm", "status")
    readonly_fields = tuple(field.name for field in LedgerSigningKey._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerCheckpoint)
class LedgerCheckpointAdmin(admin.ModelAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    list_display = ("checkpoint_number", "transaction_count", "wallet_count", "created_at")
    readonly_fields = tuple(field.name for field in LedgerCheckpoint._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

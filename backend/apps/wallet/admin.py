import uuid
from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.db.models import Prefetch
from django.utils.html import format_html
from django.utils.module_loading import import_string

from .models import (
    LedgerCheckpoint,
    LedgerSigningKey,
    Wallet,
    WalletHold,
    WalletTransaction,
)
from .services import InsufficientFunds, InvalidLedgerOperation, adjust_wallet_balance


def eur(cents):
    return f"{(Decimal(cents) / Decimal('100')):,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")


class WalletChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, wallet):
        user = wallet.customer.user
        return (
            f"{user.get_username()} ({user.email}) — "
            f"{eur(wallet.balance_cents)}"
        )


class ManualWalletAdjustmentForm(forms.Form):
    wallet = WalletChoiceField(
        queryset=Wallet.objects.select_related("customer__user").order_by(
            "customer__user__username"
        ),
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
        cents = self.cleaned_data["amount_eur"] * 100
        if cents != cents.to_integral_value():
            raise forms.ValidationError("Der Betrag muss auf volle Cent lauten.")
        return int(cents)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    change_list_template = "admin/wallet/wallet/change_list.html"
    list_display = (
        "customer_account",
        "balance_eur",
        "available_balance_eur",
        "currency",
        "manual_adjustment_link",
        "created_at",
    )
    search_fields = (
        "id",
        "customer__user__username",
        "customer__user__email",
    )
    list_select_related = ("customer__user",)
    readonly_fields = tuple(field.name for field in Wallet._meta.fields)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.prefetch_related(
            Prefetch(
                "holds",
                queryset=WalletHold.objects.filter(status=WalletHold.Status.ACTIVE),
                to_attr="active_holds",
            )
        )

    def get_urls(self):
        custom_urls = [
            path(
                "manual-adjustment/",
                self.admin_site.admin_view(self.manual_adjustment_view),
                name="wallet_manual_adjustment",
            ),
        ]
        return custom_urls + super().get_urls()

    def get_list_display(self, request):
        columns = list(super().get_list_display(request))
        if not request.user.has_perm("wallet.adjust_wallet_balance"):
            columns.remove("manual_adjustment_link")
        return tuple(columns)

    @admin.display(description="Kunde", ordering="customer__user__username")
    def customer_account(self, obj):
        user = obj.customer.user
        return f"{user.get_username()} ({user.email})"

    @admin.display(description="Kontostand", ordering="balance_cents")
    def balance_eur(self, obj):
        return eur(obj.balance_cents)

    @admin.display(description="Verfügbar")
    def available_balance_eur(self, obj):
        reserved = sum(hold.amount_cents for hold in obj.active_holds)
        return eur(obj.balance_cents - reserved)

    @admin.display(description="Aktion")
    def manual_adjustment_link(self, obj):
        url = reverse("admin:wallet_wallet_manual_adjustment")
        return format_html(
            '<a class="button" href="{}?wallet={}">Guthaben verwalten</a>',
            url,
            obj.pk,
        )

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["can_adjust_wallet"] = request.user.has_perm(
            "wallet.adjust_wallet_balance"
        )
        return super().changelist_view(request, extra_context=extra_context)

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
                        "Manuelle Buchungen bleiben bis zur Einrichtung des "
                        "Signaturdienstes deaktiviert."
                    )
                signer = import_string(signer_path)
                signing_key = LedgerSigningKey.objects.get(
                    status=LedgerSigningKey.Status.ACTIVE
                )
                configured_key_id = getattr(settings, "WALLET_LEDGER_KEY_ID", "")
                if not configured_key_id or configured_key_id != signing_key.key_id:
                    raise ImproperlyConfigured(
                        "WALLET_LEDGER_KEY_ID muss zum aktiven Ledger-Schlüssel passen."
                    )
                amount_cents = form.cleaned_data["amount_eur"]
                reason = form.cleaned_data["reason"].strip()
                if not reason:
                    form.add_error("reason", "Eine Begründung ist erforderlich.")
                else:
                    signed_amount = (
                        amount_cents
                        if form.cleaned_data["direction"] == "credit"
                        else -amount_cents
                    )
                    entry = adjust_wallet_balance(
                        form.cleaned_data["wallet"].pk,
                        signed_amount,
                        description=reason,
                        idempotency_key=str(form.cleaned_data["idempotency_key"]),
                        signing_key_id=signing_key.pk,
                        signer=signer,
                        reference=form.cleaned_data["reference"].strip(),
                        metadata={
                            "source": "django_admin_manual_adjustment",
                            "admin_user_id": str(request.user.pk),
                            "admin_username": request.user.get_username(),
                        },
                    )
                    messages.success(
                        request,
                        f"Buchung #{entry.sequence_number} gespeichert. "
                        f"Neuer Kontostand: {eur(entry.balance_after_cents)}.",
                    )
                    return HttpResponseRedirect(
                        reverse("admin:wallet_wallet_changelist")
                    )
            except (
                LedgerSigningKey.DoesNotExist,
                LedgerSigningKey.MultipleObjectsReturned,
            ):
                form.add_error(
                    None,
                    "Es muss genau ein aktiver Ledger-Signaturschlüssel vorhanden sein.",
                )
            except (InsufficientFunds, InvalidLedgerOperation) as exc:
                form.add_error(None, str(exc))
            except ImproperlyConfigured as exc:
                form.add_error(None, str(exc))
            except Exception:
                form.add_error(
                    None,
                    "Die Buchung konnte nicht sicher abgeschlossen werden. "
                    "Bitte prüfe den Ledger-Status, bevor du den Vorgang erneut startest.",
                )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Manuelle Guthabenbuchung",
            "form": form,
        }
        return render(
            request,
            "admin/wallet/wallet/manual_adjustment.html",
            context,
        )

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
    list_display = ("id", "wallet", "amount_cents", "status", "expires_at")
    list_filter = ("status",)
    readonly_fields = tuple(field.name for field in WalletHold._meta.fields)

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class TransactionDirectionFilter(admin.SimpleListFilter):
    title = "Buchungsrichtung"
    parameter_name = "direction"

    def lookups(self, request, model_admin):
        return (("credit", "Gutschriften"), ("debit", "Belastungen"))

    def queryset(self, request, queryset):
        if self.value() == "credit":
            return queryset.filter(amount_cents__gt=0)
        if self.value() == "debit":
            return queryset.filter(amount_cents__lt=0)
        return queryset


class AdminActorFilter(admin.SimpleListFilter):
    title = "Administrator"
    parameter_name = "admin_actor"

    def lookups(self, request, model_admin):
        from django.contrib.auth import get_user_model

        actors = (
            WalletTransaction.objects.filter(
                type=WalletTransaction.Type.ADMIN_ADJUSTMENT
            )
            .exclude(metadata__admin_user_id__isnull=True)
            .values_list("metadata__admin_user_id", "metadata__admin_username")
            .distinct()
            .order_by("metadata__admin_username")
        )
        return tuple(
            (str(actor_id), f"{username or 'Unbekannt'} ({actor_id})")
            for actor_id, username in actors
            if actor_id
        )

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(metadata__admin_user_id=self.value())
        return queryset


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_link",
        "created_at",
        "customer_account",
        "type",
        "direction_label",
        "formatted_amount",
        "balance_after",
        "description",
        "admin_actor",
    )
    list_display_links = ("transaction_link",)
    list_filter = (
        TransactionDirectionFilter,
        "type",
        "created_at",
        "signing_key",
        AdminActorFilter,
    )
    search_fields = (
        "id",
        "entry_hash",
        "previous_hash",
        "idempotency_key",
        "reference",
        "description",
        "wallet__id",
        "wallet__customer__user__username",
        "wallet__customer__user__email",
    )
    list_select_related = ("wallet__customer__user", "signing_key")
    readonly_fields = (
        "id",
        "wallet",
        "sequence_number",
        "type",
        "amount_cents",
        "balance_after_cents",
        "description",
        "idempotency_key",
        "reference",
        "metadata",
        "previous_hash",
        "entry_hash",
        "payload_version",
        "signature_hex",
        "signing_key",
        "created_at",
        "direction_label",
        "formatted_amount_detail",
        "admin_actor",
        "admin_user_id",
    )
    fieldsets = (
        ("Buchung", {
            "fields": (
                "id",
                "wallet",
                "sequence_number",
                "created_at",
                "type",
                "direction_label",
                "amount_cents",
                "formatted_amount_detail",
                "balance_after_cents",
                "description",
                "reference",
            ),
        }),
        ("Administrator", {
            "fields": ("admin_actor", "admin_user_id"),
        }),
        ("Idempotenz", {
            "fields": ("idempotency_key",),
        }),
        ("Kryptografische Integrität", {
            "fields": (
                "previous_hash",
                "entry_hash",
                "payload_version",
                "signing_key",
                "signature_hex",
            ),
        }),
        ("Metadaten", {
            "fields": ("metadata",),
            "classes": ("collapse",),
        }),
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-sequence_number")
    list_per_page = 50
    show_full_result_count = False
    empty_value_display = "—"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "wallet__customer__user",
            "signing_key",
        )

    @admin.display(description="Buchung", ordering="sequence_number")
    def transaction_link(self, obj):
        url = reverse("admin:wallet_wallettransaction_change", args=(obj.pk,))
        return format_html('<a href="{}">#{}</a>', url, obj.sequence_number)

    @admin.display(description="Kunde", ordering="wallet__customer__user__username")
    def customer_account(self, obj):
        user = obj.wallet.customer.user
        return f"{user.get_username()} ({user.email})"

    @admin.display(description="Richtung", ordering="amount_cents")
    def direction_label(self, obj):
        return "Gutschrift" if obj.amount_cents > 0 else "Belastung"

    @admin.display(description="Betrag", ordering="amount_cents")
    def formatted_amount(self, obj):
        return eur(obj.amount_cents)

    @admin.display(description="Betrag (formatiert)")
    def formatted_amount_detail(self, obj):
        return eur(obj.amount_cents)

    @admin.display(description="Kontostand danach", ordering="balance_after_cents")
    def balance_after(self, obj):
        return eur(obj.balance_after_cents)

    @admin.display(description="Administrator", empty_value="—")
    def admin_actor(self, obj):
        actor_id = obj.metadata.get("admin_user_id")
        if not actor_id:
            return "—"
        stored_name = obj.metadata.get("admin_username", "Unbekannt")
        return f"{stored_name} (ID: {actor_id})"

    @admin.display(description="Administrator-ID")
    def admin_user_id(self, obj):
        return obj.metadata.get("admin_user_id") or "—"

    @admin.display(description="Signatur (Hex)")
    def signature_hex(self, obj):
        signature = obj.signature
        if hasattr(signature, "tobytes"):
            signature = signature.tobytes()
        return bytes(signature).hex()

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerSigningKey)
class LedgerSigningKeyAdmin(admin.ModelAdmin):
    list_display = ("key_id", "label", "algorithm", "status", "created_at")
    list_filter = ("algorithm", "status")
    readonly_fields = tuple(field.name for field in LedgerSigningKey._meta.fields)

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerCheckpoint)
class LedgerCheckpointAdmin(admin.ModelAdmin):
    list_display = ("checkpoint_number", "transaction_count", "wallet_count", "created_at")
    readonly_fields = tuple(field.name for field in LedgerCheckpoint._meta.fields)

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

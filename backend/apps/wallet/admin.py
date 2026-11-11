from django.contrib import admin

from .models import LedgerCheckpoint, LedgerSigningKey, Wallet, WalletHold, WalletTransaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "currency", "balance_cents", "created_at")
    search_fields = ("id", "customer__user__username", "customer__user__email")
    readonly_fields = tuple(field.name for field in Wallet._meta.fields)

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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
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
    list_display = ("checkpoint_number", "transaction_count", "wallet_count", "created_at")
    readonly_fields = tuple(field.name for field in LedgerCheckpoint._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

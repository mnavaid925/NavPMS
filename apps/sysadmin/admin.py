from django.contrib import admin

from .models import (
    ApiKey, BackupPolicy, BackupRun, Currency, IdentityProvider, NumberSequence, RestoreRequest,
    RoleDefinition, RolePermission, SSOLoginEvent, SystemConfiguration, TaxCode, Webhook,
    WebhookDelivery,
)


class _AppendOnlyAdmin(admin.ModelAdmin):
    """Base for immutable log tables — no add / change / delete in the admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 0
    fields = ['permission_code']


@admin.register(RoleDefinition)
class RoleDefinitionAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'is_system', 'is_active', 'tenant']
    list_filter = ['tenant', 'is_system', 'is_active']
    search_fields = ['code', 'name']
    inlines = [RolePermissionInline]


@admin.register(IdentityProvider)
class IdentityProviderAdmin(admin.ModelAdmin):
    list_display = ['name', 'protocol', 'connector', 'is_active', 'is_default', 'tenant']
    list_filter = ['tenant', 'protocol', 'is_active']
    search_fields = ['name', 'entity_id']
    # Secrets must never surface in the admin change form.
    exclude = ['client_secret', 'bind_password']


@admin.register(SSOLoginEvent)
class SSOLoginEventAdmin(_AppendOnlyAdmin):
    list_display = ['email', 'provider', 'outcome', 'created_at', 'tenant']
    list_filter = ['tenant', 'outcome']
    search_fields = ['email', 'subject_id']
    raw_id_fields = ['provider', 'user']


@admin.register(SystemConfiguration)
class SystemConfigurationAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'base_currency_code', 'fiscal_year_start_month', 'default_payment_terms_days']
    raw_id_fields = ['default_tax_code']


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'is_base', 'exchange_rate_to_base', 'is_active', 'tenant']
    list_filter = ['tenant', 'is_base', 'is_active']
    search_fields = ['code', 'name']


@admin.register(TaxCode)
class TaxCodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'rate', 'tax_type', 'is_default', 'is_active', 'tenant']
    list_filter = ['tenant', 'tax_type', 'is_active']
    search_fields = ['code', 'name']


@admin.register(NumberSequence)
class NumberSequenceAdmin(admin.ModelAdmin):
    list_display = ['doc_type', 'name', 'prefix', 'next_number', 'is_active', 'tenant']
    list_filter = ['tenant', 'is_active', 'reset_frequency']
    search_fields = ['doc_type', 'name', 'prefix']


@admin.register(BackupPolicy)
class BackupPolicyAdmin(admin.ModelAdmin):
    list_display = ['name', 'frequency', 'scope', 'retention_days', 'is_active', 'last_run_at', 'tenant']
    list_filter = ['tenant', 'frequency', 'scope', 'is_active']
    search_fields = ['name']


@admin.register(BackupRun)
class BackupRunAdmin(_AppendOnlyAdmin):
    list_display = ['run_number', 'policy', 'status', 'trigger', 'scope', 'size_mb', 'created_at', 'tenant']
    list_filter = ['tenant', 'status', 'trigger', 'scope']
    search_fields = ['run_number', 'location']
    raw_id_fields = ['policy', 'triggered_by']


@admin.register(RestoreRequest)
class RestoreRequestAdmin(admin.ModelAdmin):
    list_display = ['backup_run', 'status', 'requested_by', 'decided_by', 'created_at', 'tenant']
    list_filter = ['tenant', 'status']
    raw_id_fields = ['backup_run', 'requested_by', 'decided_by']


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ['name', 'key_prefix', 'is_active', 'last_used_at', 'expires_at', 'tenant']
    list_filter = ['tenant', 'is_active']
    search_fields = ['name', 'key_prefix']
    # The hash is not a secret but there is no reason to edit it by hand.
    readonly_fields = ['hashed_secret', 'key_prefix']
    raw_id_fields = ['created_by']


@admin.register(Webhook)
class WebhookAdmin(admin.ModelAdmin):
    list_display = ['name', 'target_url', 'is_active', 'last_status', 'tenant']
    list_filter = ['tenant', 'is_active']
    search_fields = ['name', 'target_url']
    exclude = ['secret']  # signing secret never surfaces in the admin


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(_AppendOnlyAdmin):
    list_display = ['event', 'webhook', 'status', 'status_code', 'attempts', 'created_at', 'tenant']
    list_filter = ['tenant', 'status', 'event']
    search_fields = ['event', 'response_excerpt']
    raw_id_fields = ['webhook']

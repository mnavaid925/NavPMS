from django.contrib import admin

from .models import (
    AuditLog, BrandingSettings, HealthMetric, Invoice, Plan,
    SecuritySettings, Subscription, Transaction,
)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'price_monthly', 'price_yearly',
                    'trial_days', 'is_active', 'is_public', 'sort_order')
    list_filter = ('is_active', 'is_public', 'currency')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'plan', 'status', 'billing_cycle',
                    'started_at', 'current_period_end', 'auto_renew')
    list_filter = ('status', 'billing_cycle', 'auto_renew')
    search_fields = ('tenant__name', 'tenant__slug', 'plan__name')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'tenant', 'total', 'currency', 'status',
                    'issued_at', 'due_at', 'paid_at')
    list_filter = ('status', 'currency')
    search_fields = ('number', 'tenant__name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('gateway_ref', 'tenant', 'invoice', 'amount',
                    'currency', 'status', 'created_at')
    list_filter = ('status', 'gateway', 'currency')
    search_fields = ('gateway_ref', 'tenant__name', 'invoice__number')


@admin.register(BrandingSettings)
class BrandingAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'primary_color', 'secondary_color', 'email_from_address')


@admin.register(SecuritySettings)
class SecurityAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'password_min_length', 'mfa_required',
                    'session_timeout_minutes')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'user', 'action', 'level', 'message')
    list_filter = ('level', 'action', 'tenant')
    search_fields = ('action', 'message', 'target_id')
    readonly_fields = ('tenant', 'user', 'action', 'level', 'target_type',
                       'target_id', 'message', 'payload', 'ip_address',
                       'user_agent', 'prev_hash', 'row_hash', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HealthMetric)
class HealthMetricAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'metric_type', 'value', 'recorded_at')
    list_filter = ('metric_type', 'tenant')

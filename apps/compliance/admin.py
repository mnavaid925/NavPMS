from django.contrib import admin

from .models import (
    ComplianceScreening, FinancialRiskProfile, FinancialRiskSnapshot, FraudAlert,
    FraudAlertEvent, FraudRule, Policy, PolicyAcknowledgment, PolicyVersion,
    RestrictedPartyEntry, ScreeningMatch,
)


@admin.register(RestrictedPartyEntry)
class RestrictedPartyEntryAdmin(admin.ModelAdmin):
    list_display = ['entity_name', 'list_name', 'entry_type', 'country', 'is_active', 'tenant']
    list_filter = ['tenant', 'list_name', 'entry_type', 'is_active']
    search_fields = ['entity_name', 'list_name', 'source_ref']


class ScreeningMatchInline(admin.TabularInline):
    model = ScreeningMatch
    extra = 0
    raw_id_fields = ['entry', 'dispositioned_by']


@admin.register(ComplianceScreening)
class ComplianceScreeningAdmin(admin.ModelAdmin):
    list_display = ['screening_number', 'screened_name', 'vendor', 'status', 'match_count',
                    'screened_at', 'tenant']
    list_filter = ['tenant', 'status', 'provider']
    search_fields = ['screening_number', 'screened_name']
    raw_id_fields = ['vendor', 'screened_by']
    inlines = [ScreeningMatchInline]


@admin.register(FinancialRiskProfile)
class FinancialRiskProfileAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'band', 'credit_score', 'outlook', 'exposure_amount', 'monitored',
                    'last_checked_at', 'tenant']
    list_filter = ['tenant', 'band', 'outlook', 'monitored']
    search_fields = ['vendor__legal_name']
    raw_id_fields = ['vendor']


@admin.register(FinancialRiskSnapshot)
class FinancialRiskSnapshotAdmin(admin.ModelAdmin):
    """Append-only financial-risk history."""

    list_display = ['vendor', 'as_of_date', 'credit_score', 'band', 'exposure_amount', 'tenant']
    list_filter = ['tenant', 'band']
    search_fields = ['vendor__legal_name']
    raw_id_fields = ['vendor', 'profile']
    date_hierarchy = 'as_of_date'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FraudRule)
class FraudRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'severity', 'is_active', 'display_order', 'tenant']
    list_filter = ['tenant', 'code', 'severity', 'is_active']
    search_fields = ['name', 'code']


@admin.register(FraudAlert)
class FraudAlertAdmin(admin.ModelAdmin):
    list_display = ['alert_number', 'rule_code', 'severity', 'status', 'vendor', 'detected_at',
                    'tenant']
    list_filter = ['tenant', 'status', 'severity', 'rule_code']
    search_fields = ['alert_number', 'summary', 'signature']
    raw_id_fields = ['rule', 'vendor', 'assigned_to', 'resolved_by']


@admin.register(FraudAlertEvent)
class FraudAlertEventAdmin(admin.ModelAdmin):
    """Append-only investigation timeline."""

    list_display = ['alert', 'from_status', 'to_status', 'actor', 'created_at', 'tenant']
    list_filter = ['tenant', 'to_status']
    search_fields = ['alert__alert_number', 'note']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PolicyVersionInline(admin.TabularInline):
    model = PolicyVersion
    extra = 0
    fk_name = 'policy'
    raw_id_fields = ['published_by']


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ['policy_number', 'title', 'category', 'status', 'requires_acknowledgment',
                    'owner', 'tenant']
    list_filter = ['tenant', 'status', 'category', 'requires_acknowledgment']
    search_fields = ['policy_number', 'title']
    raw_id_fields = ['owner', 'created_by', 'current_version']
    inlines = [PolicyVersionInline]


@admin.register(PolicyAcknowledgment)
class PolicyAcknowledgmentAdmin(admin.ModelAdmin):
    """Append-only sign-off ledger."""

    list_display = ['policy_version', 'user', 'acknowledged_at', 'ip_address', 'tenant']
    list_filter = ['tenant']
    search_fields = ['user__username', 'policy_version__policy__policy_number']
    raw_id_fields = ['policy_version', 'user']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

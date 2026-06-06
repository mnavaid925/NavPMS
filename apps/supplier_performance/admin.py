from django.contrib import admin

from .models import (
    ImprovementPlan, KpiDefinition, PerformanceFeedback, PIPAction, PIPStatusEvent,
    Scorecard, ScorecardLine,
)


@admin.register(KpiDefinition)
class KpiDefinitionAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'kpi_type', 'source', 'direction', 'weight', 'target_value',
                    'is_active', 'tenant']
    list_filter = ['tenant', 'kpi_type', 'source', 'is_active']
    search_fields = ['code', 'name', 'description']


class ScorecardLineInline(admin.TabularInline):
    model = ScorecardLine
    extra = 0
    raw_id_fields = ['kpi']
    readonly_fields = ['kpi_code', 'kpi_name', 'raw_value', 'score', 'weight', 'weighted_score']


@admin.register(Scorecard)
class ScorecardAdmin(admin.ModelAdmin):
    list_display = ['scorecard_number', 'vendor', 'period_label', 'status', 'overall_score',
                    'rating_band', 'is_current', 'tenant']
    list_filter = ['tenant', 'status', 'rating_band', 'is_current']
    search_fields = ['scorecard_number', 'vendor__legal_name']
    raw_id_fields = ['vendor', 'generated_by']
    inlines = [ScorecardLineInline]


@admin.register(PerformanceFeedback)
class PerformanceFeedbackAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'reviewer', 'status', 'rating', 'period_label', 'submitted_at',
                    'tenant']
    list_filter = ['tenant', 'status']
    search_fields = ['vendor__legal_name', 'comments']
    raw_id_fields = ['vendor', 'reviewer', 'requested_by']


class PIPActionInline(admin.TabularInline):
    model = PIPAction
    extra = 0
    raw_id_fields = ['assigned_to']


@admin.register(ImprovementPlan)
class ImprovementPlanAdmin(admin.ModelAdmin):
    list_display = ['pip_number', 'vendor', 'title', 'status', 'severity', 'owner', 'target_date',
                    'tenant']
    list_filter = ['tenant', 'status', 'severity']
    search_fields = ['pip_number', 'title', 'vendor__legal_name']
    raw_id_fields = ['vendor', 'scorecard', 'owner', 'created_by']
    inlines = [PIPActionInline]


@admin.register(PIPStatusEvent)
class PIPStatusEventAdmin(admin.ModelAdmin):
    """Append-only timeline."""

    list_display = ['improvement_plan', 'from_status', 'to_status', 'actor', 'created_at', 'tenant']
    list_filter = ['tenant', 'to_status']
    search_fields = ['improvement_plan__pip_number', 'note']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

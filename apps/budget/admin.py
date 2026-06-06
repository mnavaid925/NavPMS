from django.contrib import admin

from .models import (
    Budget, BudgetAllocation, BudgetCheck, BudgetPeriod, BudgetStatusEvent,
)


@admin.register(BudgetPeriod)
class BudgetPeriodAdmin(admin.ModelAdmin):
    list_display = ['name', 'period_type', 'start_date', 'end_date', 'status', 'is_default',
                    'tenant']
    list_filter = ['tenant', 'period_type', 'status']
    search_fields = ['name']


class BudgetAllocationInline(admin.TabularInline):
    model = BudgetAllocation
    extra = 0
    raw_id_fields = ['account_code', 'vendor_category']


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ['budget_number', 'name', 'period', 'status', 'total_allocated', 'currency',
                    'owner', 'tenant']
    list_filter = ['tenant', 'status', 'period']
    search_fields = ['budget_number', 'name', 'description']
    raw_id_fields = ['owner', 'created_by']
    inlines = [BudgetAllocationInline]


@admin.register(BudgetStatusEvent)
class BudgetStatusEventAdmin(admin.ModelAdmin):
    """Append-only timeline."""

    list_display = ['budget', 'from_status', 'to_status', 'actor', 'created_at', 'tenant']
    list_filter = ['tenant', 'to_status']
    search_fields = ['budget__budget_number', 'note']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BudgetCheck)
class BudgetCheckAdmin(admin.ModelAdmin):
    """Read-only availability-check evidence."""

    list_display = ['created_at', 'requisition', 'account_code', 'requested_amount',
                    'available_amount', 'result', 'enforcement_mode', 'tenant']
    list_filter = ['tenant', 'result', 'enforcement_mode']
    search_fields = ['requisition__number', 'message']
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

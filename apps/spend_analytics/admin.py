from django.contrib import admin

from .models import SpendRecord, SpendReport


@admin.register(SpendRecord)
class SpendRecordAdmin(admin.ModelAdmin):
    """Read-only — SpendRecord is a synced projection, not hand-edited."""

    list_display = [
        'source_ref', 'source_type', 'basis', 'spend_date', 'vendor_name', 'amount',
        'currency', 'is_maverick', 'tenant',
    ]
    list_filter = [
        'tenant', 'source_type', 'basis', 'is_maverick', 'off_contract',
        'off_preferred_supplier', 'off_po',
    ]
    search_fields = ['source_ref', 'vendor_name', 'description']
    date_hierarchy = 'spend_date'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SpendReport)
class SpendReportAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'dimension', 'measure', 'basis', 'chart_type', 'is_shared', 'owner',
        'last_run_at', 'tenant',
    ]
    list_filter = ['tenant', 'dimension', 'measure', 'basis', 'is_shared']
    search_fields = ['name', 'description']
    raw_id_fields = ['vendor', 'vendor_category', 'vendor_segment', 'account_code', 'owner']

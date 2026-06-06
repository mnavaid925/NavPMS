from django.contrib import admin

from .models import (
    CycleCount, CycleCountLine, CycleCountStatusEvent, GoodsIssue, GoodsIssueLine,
    GoodsIssueStatusEvent, StockItem, StockLevel, StockMovement, Warehouse, WarehouseLocation,
)


class WarehouseLocationInline(admin.TabularInline):
    model = WarehouseLocation
    extra = 0


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'is_active', 'is_default', 'tenant']
    list_filter = ['tenant', 'is_active', 'is_default']
    search_fields = ['code', 'name']
    inlines = [WarehouseLocationInline]


@admin.register(WarehouseLocation)
class WarehouseLocationAdmin(admin.ModelAdmin):
    list_display = ['code', 'warehouse', 'aisle', 'rack', 'shelf', 'is_active', 'tenant']
    list_filter = ['tenant', 'warehouse', 'is_active']
    search_fields = ['code', 'description']
    raw_id_fields = ['warehouse']


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ['sku', 'catalog_item', 'quantity_on_hand', 'reorder_point', 'is_stocked',
                    'moving_avg_cost', 'tenant']
    list_filter = ['tenant', 'is_stocked', 'abc_class']
    search_fields = ['sku', 'catalog_item__name', 'catalog_item__item_number']
    raw_id_fields = ['catalog_item', 'default_warehouse', 'default_location', 'reorder_requisition']


@admin.register(StockLevel)
class StockLevelAdmin(admin.ModelAdmin):
    list_display = ['stock_item', 'warehouse', 'location', 'lot_number', 'expiry_date', 'quantity',
                    'condition', 'tenant']
    list_filter = ['tenant', 'warehouse', 'condition']
    search_fields = ['stock_item__sku', 'lot_number', 'serial_number']
    raw_id_fields = ['stock_item', 'warehouse', 'location']


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """Append-only stock ledger."""

    list_display = ['number', 'movement_type', 'stock_item', 'warehouse', 'quantity',
                    'balance_after', 'created_at', 'tenant']
    list_filter = ['tenant', 'movement_type', 'warehouse']
    search_fields = ['number', 'stock_item__sku', 'reason']
    raw_id_fields = ['stock_item', 'warehouse', 'location', 'to_location',
                     'source_goods_receipt_line', 'goods_issue_line', 'cycle_count_line', 'actor']
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class GoodsIssueLineInline(admin.TabularInline):
    model = GoodsIssueLine
    extra = 0
    raw_id_fields = ['stock_item', 'location']


@admin.register(GoodsIssue)
class GoodsIssueAdmin(admin.ModelAdmin):
    list_display = ['number', 'issue_type', 'warehouse', 'status', 'issued_at', 'tenant']
    list_filter = ['tenant', 'status', 'issue_type', 'warehouse']
    search_fields = ['number', 'purpose']
    raw_id_fields = ['warehouse', 'requested_by', 'issued_by', 'created_by']
    inlines = [GoodsIssueLineInline]


class CycleCountLineInline(admin.TabularInline):
    model = CycleCountLine
    extra = 0
    raw_id_fields = ['stock_item', 'location']


@admin.register(CycleCount)
class CycleCountAdmin(admin.ModelAdmin):
    list_display = ['number', 'warehouse', 'scope', 'status', 'posted_at', 'tenant']
    list_filter = ['tenant', 'status', 'scope', 'warehouse']
    search_fields = ['number']
    raw_id_fields = ['warehouse', 'counted_by', 'posted_by', 'created_by']
    inlines = [CycleCountLineInline]


@admin.register(GoodsIssueStatusEvent)
class GoodsIssueStatusEventAdmin(admin.ModelAdmin):
    """Append-only goods-issue timeline."""

    list_display = ['goods_issue', 'from_status', 'to_status', 'actor', 'created_at', 'tenant']
    list_filter = ['tenant', 'to_status']
    search_fields = ['goods_issue__number']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CycleCountStatusEvent)
class CycleCountStatusEventAdmin(admin.ModelAdmin):
    """Append-only cycle-count timeline."""

    list_display = ['cycle_count', 'from_status', 'to_status', 'actor', 'created_at', 'tenant']
    list_filter = ['tenant', 'to_status']
    search_fields = ['cycle_count__number']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

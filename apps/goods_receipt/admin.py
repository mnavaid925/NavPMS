"""Module 13 admin registrations.

The status-event timeline is append-only (add/change/delete disabled, mirroring
``ShipmentStatusEvent`` / ``PurchaseOrderStatusEvent``).
"""
from django.contrib import admin

from .models import (
    GoodsReceipt,
    GoodsReceiptCheck,
    GoodsReceiptLine,
    GoodsReceiptStatusEvent,
    ReceiptTag,
    ReturnToVendor,
    ReturnToVendorLine,
)


class GoodsReceiptLineInline(admin.TabularInline):
    model = GoodsReceiptLine
    extra = 0
    fields = [
        'line_no', 'purchase_order_line', 'description', 'uom', 'received_quantity',
        'accepted_quantity', 'rejected_quantity', 'posted_quantity', 'discrepancy_type',
        'line_status',
    ]
    readonly_fields = ['posted_quantity']


class GoodsReceiptCheckInline(admin.TabularInline):
    model = GoodsReceiptCheck
    extra = 0
    fields = ['criterion', 'result', 'note', 'checked_by']


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(admin.ModelAdmin):
    list_display = [
        'grn_number', 'purchase_order', 'vendor', 'status', 'inspection_result',
        'received_date', 'posted_at', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'inspection_result']
    search_fields = [
        'grn_number', 'purchase_order__po_number', 'vendor__legal_name',
        'delivery_note_ref',
    ]
    readonly_fields = [
        'grn_number', 'received_at', 'inspected_at', 'posted_at', 'cancelled_at',
        'closed_at', 'inspection_alerted_at',
    ]
    inlines = [GoodsReceiptLineInline, GoodsReceiptCheckInline]


class ReturnToVendorLineInline(admin.TabularInline):
    model = ReturnToVendorLine
    extra = 0
    fields = ['line_no', 'goods_receipt_line', 'description', 'uom', 'quantity', 'reason']


@admin.register(ReturnToVendor)
class ReturnToVendorAdmin(admin.ModelAdmin):
    list_display = [
        'rtv_number', 'goods_receipt', 'vendor', 'status', 'rma_number',
        'authorized_at', 'shipped_at', 'tenant',
    ]
    list_filter = ['tenant', 'status']
    search_fields = ['rtv_number', 'goods_receipt__grn_number', 'vendor__legal_name']
    readonly_fields = [
        'rtv_number', 'authorized_at', 'shipped_at', 'closed_at', 'cancelled_at',
        'acknowledged_at', 'alerted_at',
    ]
    inlines = [ReturnToVendorLineInline]


@admin.register(ReceiptTag)
class ReceiptTagAdmin(admin.ModelAdmin):
    list_display = ['code', 'goods_receipt', 'goods_receipt_line', 'quantity', 'tenant']
    list_filter = ['tenant']
    search_fields = ['code', 'goods_receipt__grn_number']
    readonly_fields = ['code', 'generated_by']


@admin.register(GoodsReceiptCheck)
class GoodsReceiptCheckAdmin(admin.ModelAdmin):
    list_display = ['goods_receipt', 'criterion', 'result', 'checked_by', 'tenant']
    list_filter = ['tenant', 'result', 'criterion']
    search_fields = ['goods_receipt__grn_number']


@admin.register(GoodsReceiptStatusEvent)
class GoodsReceiptStatusEventAdmin(admin.ModelAdmin):
    list_display = ['goods_receipt', 'status', 'actor', 'created_at', 'tenant']
    list_filter = ['tenant', 'status']
    search_fields = ['goods_receipt__grn_number', 'note']
    readonly_fields = ['goods_receipt', 'status', 'note', 'actor', 'created_at']

    def has_add_permission(self, request):
        return False  # append-only

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False  # append-only

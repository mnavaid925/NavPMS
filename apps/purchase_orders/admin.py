"""Module 11 admin registrations.

The status-event timeline is append-only (add/change/delete disabled, mirroring
``AuditLog`` / ``ContractStatusEvent``); an applied change order is frozen
(change/delete disabled once ``applied``).
"""
from django.contrib import admin

from .models import (
    PurchaseOrder,
    PurchaseOrderChangeOrder,
    PurchaseOrderDocument,
    PurchaseOrderLine,
    PurchaseOrderStatusEvent,
)


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0
    fields = [
        'line_no', 'description', 'uom', 'quantity', 'unit_price', 'line_total',
        'delivery_status', 'received_quantity',
    ]
    readonly_fields = ['line_total']


class PurchaseOrderChangeOrderInline(admin.TabularInline):
    model = PurchaseOrderChangeOrder
    extra = 0
    fields = ['change_number', 'change_type', 'status', 'new_total', 'applied_at']
    readonly_fields = ['change_number', 'new_total', 'applied_at']
    show_change_link = True


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = [
        'po_number', 'title', 'status', 'vendor', 'currency', 'total_amount',
        'expected_delivery_date', 'revision', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'dispatch_method']
    search_fields = ['po_number', 'title', 'description', 'vendor__legal_name']
    readonly_fields = [
        'po_number', 'revision', 'subtotal', 'total_amount', 'issued_at',
        'acknowledged_at', 'declined_at', 'closed_at', 'cancelled_at',
        'ack_alerted_at', 'delivery_alerted_at',
    ]
    inlines = [PurchaseOrderLineInline, PurchaseOrderChangeOrderInline]


@admin.register(PurchaseOrderChangeOrder)
class PurchaseOrderChangeOrderAdmin(admin.ModelAdmin):
    list_display = [
        'change_number', 'purchase_order', 'change_type', 'status',
        'new_total', 'applied_at', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'change_type']
    search_fields = ['change_number', 'purchase_order__po_number', 'reason']
    readonly_fields = [
        'change_number', 'prev_expected_delivery_date', 'prev_lines', 'prev_total',
        'new_total', 'applied_at', 'applied_by',
    ]

    def has_change_permission(self, request, obj=None):
        # An applied change order is an immutable part of the version history.
        if obj is not None and obj.is_applied:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_applied:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(PurchaseOrderDocument)
class PurchaseOrderDocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'purchase_order', 'uploaded_by', 'uploaded_at', 'tenant']
    list_filter = ['tenant']
    search_fields = ['title', 'purchase_order__po_number']
    readonly_fields = ['uploaded_at']


@admin.register(PurchaseOrderStatusEvent)
class PurchaseOrderStatusEventAdmin(admin.ModelAdmin):
    list_display = ['purchase_order', 'status', 'actor', 'created_at', 'tenant']
    list_filter = ['tenant', 'status']
    search_fields = ['purchase_order__po_number', 'note']
    readonly_fields = [
        'purchase_order', 'change_order', 'status', 'note', 'actor', 'created_at',
    ]

    def has_add_permission(self, request):
        return False  # append-only

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False  # append-only

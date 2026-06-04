"""Module 12 admin registrations.

The tracking ledger and the status-event timeline are append-only (add/change/delete
disabled, mirroring ``AuditLog`` / ``PurchaseOrderStatusEvent``).
"""
from django.contrib import admin

from .models import (
    Backorder,
    Shipment,
    ShipmentDocument,
    ShipmentLine,
    ShipmentStatusEvent,
    ShipmentTrackingEvent,
)


class ShipmentLineInline(admin.TabularInline):
    model = ShipmentLine
    extra = 0
    fields = [
        'line_no', 'purchase_order_line', 'description', 'uom', 'shipped_quantity',
        'received_quantity', 'posted_quantity', 'line_status',
    ]
    readonly_fields = ['posted_quantity']


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = [
        'shipment_number', 'purchase_order', 'vendor', 'status', 'carrier',
        'tracking_number', 'estimated_delivery_date', 'actual_delivery_date', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'carrier', 'received_condition']
    search_fields = [
        'shipment_number', 'purchase_order__po_number', 'vendor__legal_name',
        'tracking_number',
    ]
    readonly_fields = [
        'shipment_number', 'advised_at', 'delivered_at', 'tracking_last_synced_at',
        'cancelled_at', 'closed_at', 'delivery_alerted_at',
    ]
    inlines = [ShipmentLineInline]


@admin.register(Backorder)
class BackorderAdmin(admin.ModelAdmin):
    list_display = [
        'purchase_order', 'purchase_order_line', 'quantity', 'status',
        'expected_date', 'fulfilled_by_shipment', 'tenant',
    ]
    list_filter = ['tenant', 'status']
    search_fields = ['purchase_order__po_number', 'reason']
    readonly_fields = ['fulfilled_at', 'alerted_at']


@admin.register(ShipmentDocument)
class ShipmentDocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'shipment', 'doc_type', 'uploaded_by', 'uploaded_at', 'tenant']
    list_filter = ['tenant', 'doc_type']
    search_fields = ['title', 'shipment__shipment_number']
    readonly_fields = ['uploaded_at']


@admin.register(ShipmentTrackingEvent)
class ShipmentTrackingEventAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'status_code', 'location', 'occurred_at', 'source', 'tenant']
    list_filter = ['tenant', 'source', 'status_code']
    search_fields = ['shipment__shipment_number', 'status_code', 'description']
    readonly_fields = [
        'shipment', 'status_code', 'description', 'location', 'occurred_at', 'source',
        'raw', 'recorded_by', 'created_at',
    ]

    def has_add_permission(self, request):
        return False  # append-only

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False  # append-only


@admin.register(ShipmentStatusEvent)
class ShipmentStatusEventAdmin(admin.ModelAdmin):
    list_display = ['shipment', 'status', 'actor', 'created_at', 'tenant']
    list_filter = ['tenant', 'status']
    search_fields = ['shipment__shipment_number', 'note']
    readonly_fields = ['shipment', 'status', 'note', 'actor', 'created_at']

    def has_add_permission(self, request):
        return False  # append-only

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False  # append-only

"""Module 14 admin registrations.

The status-event timelines and the dispute thread are append-only (add/change/delete
disabled, mirroring ``GoodsReceiptStatusEventAdmin`` / ``PurchaseOrderStatusEvent``).
"""
from django.contrib import admin

from .models import (
    InvoiceDisputeNote,
    PaymentTerm,
    PaymentVoucher,
    PaymentVoucherStatusEvent,
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierInvoiceStatusEvent,
)


@admin.register(PaymentTerm)
class PaymentTermAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'name', 'net_days', 'discount_percent', 'discount_days',
        'is_active', 'tenant',
    ]
    list_filter = ['tenant', 'is_active']
    search_fields = ['code', 'name']


class SupplierInvoiceLineInline(admin.TabularInline):
    model = SupplierInvoiceLine
    extra = 0
    fields = [
        'line_no', 'purchase_order_line', 'description', 'uom', 'quantity', 'unit_price',
        'line_total', 'tax_amount', 'match_status',
    ]
    readonly_fields = ['line_total', 'match_status']


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = [
        'invoice_number', 'supplier_invoice_ref', 'vendor', 'purchase_order', 'status',
        'match_status', 'total_amount', 'due_date', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'match_status']
    search_fields = [
        'invoice_number', 'supplier_invoice_ref', 'purchase_order__po_number',
        'vendor__legal_name',
    ]
    readonly_fields = [
        'invoice_number', 'submitted_at', 'approved_at', 'disputed_at', 'resolved_at',
        'paid_at', 'rejected_at', 'cancelled_at', 'overdue_alerted_at',
        'discount_alerted_at',
    ]
    inlines = [SupplierInvoiceLineInline]


@admin.register(PaymentVoucher)
class PaymentVoucherAdmin(admin.ModelAdmin):
    list_display = [
        'voucher_number', 'supplier_invoice', 'vendor', 'status', 'amount',
        'payment_method', 'paid_date', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'payment_method']
    search_fields = [
        'voucher_number', 'supplier_invoice__invoice_number', 'vendor__legal_name',
        'gateway_ref',
    ]
    readonly_fields = [
        'voucher_number', 'approved_at', 'paid_at', 'paid_date', 'cancelled_at',
        'gateway', 'gateway_ref',
    ]


@admin.register(InvoiceDisputeNote)
class InvoiceDisputeNoteAdmin(admin.ModelAdmin):
    list_display = ['supplier_invoice', 'is_from_vendor', 'author', 'created_at', 'tenant']
    list_filter = ['tenant', 'is_from_vendor']
    search_fields = ['supplier_invoice__invoice_number', 'body']
    readonly_fields = ['supplier_invoice', 'author', 'is_from_vendor', 'body', 'created_at']

    def has_add_permission(self, request):
        return False  # append-only

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False  # append-only


class _AppendOnlyStatusEventAdmin(admin.ModelAdmin):
    list_filter = ['tenant', 'status']
    readonly_fields = ['status', 'note', 'actor', 'created_at']

    def has_add_permission(self, request):
        return False  # append-only

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False  # append-only


@admin.register(SupplierInvoiceStatusEvent)
class SupplierInvoiceStatusEventAdmin(_AppendOnlyStatusEventAdmin):
    list_display = ['supplier_invoice', 'status', 'actor', 'created_at', 'tenant']
    search_fields = ['supplier_invoice__invoice_number', 'note']
    readonly_fields = ['supplier_invoice', 'status', 'note', 'actor', 'created_at']


@admin.register(PaymentVoucherStatusEvent)
class PaymentVoucherStatusEventAdmin(_AppendOnlyStatusEventAdmin):
    list_display = ['payment_voucher', 'status', 'actor', 'created_at', 'tenant']
    search_fields = ['payment_voucher__voucher_number', 'note']
    readonly_fields = ['payment_voucher', 'status', 'note', 'actor', 'created_at']

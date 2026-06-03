"""Admin registrations for Module 10: Catalog Management.

The ``CatalogItem`` carries price-tier and price-change inlines. The append-only
``CatalogItemStatusEvent`` timeline has add/change/delete disabled (like
``ContractStatusEvent`` / ``AuditLog``), an applied ``CatalogPriceChangeRequest``
becomes read-only, and ``SupplierPunchoutConfig.shared_secret`` is excluded from
the admin entirely so the credential is never rendered.
"""
from django.contrib import admin

from .models import (
    CatalogCategory,
    CatalogItem,
    CatalogItemStatusEvent,
    CatalogPriceChangeRequest,
    CatalogPriceTier,
    PunchoutSession,
    SupplierCatalogUpload,
    SupplierPunchoutConfig,
)


class CatalogPriceTierInline(admin.TabularInline):
    model = CatalogPriceTier
    extra = 0
    fields = ['tier_type', 'min_quantity', 'unit_price', 'contract',
              'effective_from', 'effective_to', 'is_active']


class CatalogPriceChangeRequestInline(admin.TabularInline):
    model = CatalogPriceChangeRequest
    extra = 0
    fields = ['request_number', 'change_type', 'new_base_price', 'status']
    readonly_fields = ['request_number']


@admin.register(CatalogItem)
class CatalogItemAdmin(admin.ModelAdmin):
    list_display = [
        'item_number', 'name', 'source', 'status', 'vendor', 'category',
        'currency', 'base_price', 'is_active', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'source', 'is_active']
    search_fields = ['item_number', 'name', 'sku', 'vendor__legal_name']
    readonly_fields = [
        'item_number', 'submitted_at', 'approved_at', 'rejected_at', 'retired_at',
    ]
    inlines = [CatalogPriceTierInline, CatalogPriceChangeRequestInline]


@admin.register(CatalogCategory)
class CatalogCategoryAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'parent', 'is_active', 'tenant']
    list_filter = ['tenant', 'is_active']
    search_fields = ['code', 'name']


@admin.register(CatalogPriceTier)
class CatalogPriceTierAdmin(admin.ModelAdmin):
    list_display = ['item', 'tier_type', 'min_quantity', 'unit_price',
                    'effective_from', 'effective_to', 'is_active']
    list_filter = ['tenant', 'tier_type', 'is_active']
    search_fields = ['item__item_number', 'item__name']


@admin.register(CatalogPriceChangeRequest)
class CatalogPriceChangeRequestAdmin(admin.ModelAdmin):
    list_display = ['request_number', 'item', 'change_type', 'status', 'decided_at']
    list_filter = ['tenant', 'status', 'change_type']
    search_fields = ['request_number', 'item__item_number']
    readonly_fields = ['request_number', 'prev_base_price', 'prev_tiers',
                       'decided_at', 'decided_by']

    def has_change_permission(self, request, obj=None):
        # Applied price changes are an immutable part of the price history.
        if obj is not None and obj.is_applied:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_applied:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(SupplierPunchoutConfig)
class SupplierPunchoutConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'vendor', 'protocol', 'is_active', 'tenant']
    list_filter = ['tenant', 'protocol', 'is_active']
    search_fields = ['name', 'vendor__legal_name', 'setup_url']
    # WARNING: shared_secret is a credential — excluded so it is never rendered.
    exclude = ['shared_secret']


@admin.register(PunchoutSession)
class PunchoutSessionAdmin(admin.ModelAdmin):
    list_display = ['id', 'config', 'vendor', 'status', 'started_by', 'created_at']
    list_filter = ['tenant', 'status']
    search_fields = ['buyer_cookie', 'vendor__legal_name']
    readonly_fields = [
        'buyer_cookie', 'return_token', 'start_page_url', 'cart_data',
        'redirected_at', 'returned_at', 'expires_at',
    ]


@admin.register(SupplierCatalogUpload)
class SupplierCatalogUploadAdmin(admin.ModelAdmin):
    list_display = ['id', 'vendor', 'original_filename', 'status', 'row_count',
                    'imported_count', 'error_count', 'tenant']
    list_filter = ['tenant', 'status']
    search_fields = ['vendor__legal_name', 'original_filename']
    readonly_fields = ['row_count', 'imported_count', 'error_count', 'error_log',
                       'processed_at']


@admin.register(CatalogItemStatusEvent)
class CatalogItemStatusEventAdmin(admin.ModelAdmin):
    list_display = ['item', 'status', 'actor', 'created_at']
    list_filter = ['tenant', 'status']
    search_fields = ['item__item_number', 'note']
    readonly_fields = ['item', 'price_change', 'status', 'note', 'actor', 'created_at']

    def has_add_permission(self, request):
        return False  # append-only

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False  # append-only

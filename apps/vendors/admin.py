"""Admin registrations for Module 5: Vendor Management."""
from django.contrib import admin

from .models import (
    Vendor, VendorBankAccount, VendorBlacklistEvent, VendorCategory,
    VendorContact, VendorDocument, VendorOnboardingApplication,
    VendorRiskAssessment, VendorSegment,
)


class VendorContactInline(admin.TabularInline):
    model = VendorContact
    extra = 0
    fields = ['name', 'role', 'email', 'phone', 'is_primary']


class VendorDocumentInline(admin.TabularInline):
    model = VendorDocument
    extra = 0
    fields = ['doc_type', 'title', 'expires_at', 'is_verified']
    readonly_fields = ['is_verified']


class VendorBankAccountInline(admin.TabularInline):
    model = VendorBankAccount
    extra = 0
    fields = ['bank_name', 'account_holder', 'account_number', 'currency', 'is_primary']


@admin.register(VendorCategory)
class VendorCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'parent', 'tenant', 'is_active']
    list_filter = ['tenant', 'is_active']
    search_fields = ['name', 'code']


@admin.register(VendorSegment)
class VendorSegmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'color', 'tenant', 'is_active']
    list_filter = ['tenant', 'is_active', 'color']
    search_fields = ['name', 'code']


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = [
        'vendor_number', 'legal_name', 'vendor_type', 'category', 'segment',
        'status', 'risk_level', 'is_verified', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'risk_level', 'vendor_type', 'is_verified']
    search_fields = ['vendor_number', 'legal_name', 'trade_name', 'email', 'tax_id']
    readonly_fields = ['vendor_number', 'risk_score', 'risk_level', 'is_verified',
                       'verified_at', 'verified_by']
    inlines = [VendorContactInline, VendorDocumentInline, VendorBankAccountInline]


@admin.register(VendorOnboardingApplication)
class VendorOnboardingApplicationAdmin(admin.ModelAdmin):
    list_display = [
        'company_name', 'contact_email', 'vendor_type', 'status',
        'submitted_at', 'reviewed_by', 'converted_to_vendor', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'vendor_type']
    search_fields = ['company_name', 'contact_email', 'tax_id']
    readonly_fields = ['token', 'submitted_at']


@admin.register(VendorRiskAssessment)
class VendorRiskAssessmentAdmin(admin.ModelAdmin):
    list_display = [
        'vendor', 'assessment_date', 'overall_score', 'level', 'is_current',
        'assessed_by',
    ]
    list_filter = ['tenant', 'level', 'is_current']
    search_fields = ['vendor__legal_name', 'vendor__vendor_number']
    readonly_fields = ['overall_score', 'level']


@admin.register(VendorBlacklistEvent)
class VendorBlacklistEventAdmin(admin.ModelAdmin):
    list_display = [
        'vendor', 'action', 'effective_date', 'end_date', 'actioned_by', 'tenant',
    ]
    list_filter = ['tenant', 'action']
    search_fields = ['vendor__legal_name', 'vendor__vendor_number', 'reason']
    readonly_fields = ['created_at']

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VendorContact)
class VendorContactAdmin(admin.ModelAdmin):
    list_display = ['name', 'vendor', 'role', 'email', 'is_primary']
    search_fields = ['name', 'email', 'vendor__legal_name']


@admin.register(VendorDocument)
class VendorDocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'vendor', 'doc_type', 'expires_at', 'is_verified']
    list_filter = ['doc_type', 'is_verified']
    search_fields = ['title', 'vendor__legal_name']


@admin.register(VendorBankAccount)
class VendorBankAccountAdmin(admin.ModelAdmin):
    list_display = ['bank_name', 'vendor', 'account_number', 'currency', 'is_primary']
    search_fields = ['bank_name', 'account_number', 'vendor__legal_name']

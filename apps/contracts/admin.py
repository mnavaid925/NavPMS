"""Admin registrations for Module 9: Contract Management.

The parent ``Contract`` carries clause / signatory / obligation inlines. The
append-only ``ContractStatusEvent`` timeline has add/change/delete disabled (like
``AuditLog`` / ``AuctionBid``), and an applied ``ContractAmendment`` becomes
read-only so the version history can't be rewritten.
"""
from django.contrib import admin

from .models import (
    Contract,
    ContractAmendment,
    ContractClause,
    ContractClauseLine,
    ContractDocument,
    ContractObligation,
    ContractSignatory,
    ContractStatusEvent,
    ContractTemplate,
    ContractTemplateClause,
)


class ContractClauseLineInline(admin.TabularInline):
    model = ContractClauseLine
    extra = 0
    fields = ['sort_order', 'heading', 'clause']


class ContractSignatoryInline(admin.TabularInline):
    model = ContractSignatory
    extra = 0
    fields = ['order', 'party', 'name', 'email', 'status', 'signed_at']
    readonly_fields = ['signed_at']


class ContractObligationInline(admin.TabularInline):
    model = ContractObligation
    extra = 0
    fields = ['obligation_type', 'title', 'due_date', 'amount', 'status']


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = [
        'contract_number', 'title', 'contract_type', 'status', 'vendor',
        'currency', 'value', 'end_date', 'revision', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'contract_type', 'auto_renew']
    search_fields = ['contract_number', 'title', 'description', 'vendor__legal_name']
    readonly_fields = [
        'contract_number', 'revision', 'signature_sent_at', 'signed_at',
        'activated_at', 'terminated_at', 'cancelled_at', 'renewal_alerted_at',
    ]
    inlines = [
        ContractClauseLineInline, ContractSignatoryInline, ContractObligationInline,
    ]


@admin.register(ContractClause)
class ContractClauseAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'is_standard', 'is_active', 'tenant']
    list_filter = ['tenant', 'category', 'is_standard', 'is_active']
    search_fields = ['title', 'body']


class ContractTemplateClauseInline(admin.TabularInline):
    model = ContractTemplateClause
    extra = 0
    fields = ['sort_order', 'heading', 'clause']


@admin.register(ContractTemplate)
class ContractTemplateAdmin(admin.ModelAdmin):
    list_display = ['title', 'contract_type', 'is_shared', 'archived', 'tenant']
    list_filter = ['tenant', 'contract_type', 'is_shared', 'archived']
    search_fields = ['title', 'description']
    inlines = [ContractTemplateClauseInline]


@admin.register(ContractSignatory)
class ContractSignatoryAdmin(admin.ModelAdmin):
    list_display = ['contract', 'order', 'party', 'name', 'status', 'signed_at']
    list_filter = ['tenant', 'party', 'status']
    search_fields = ['name', 'email', 'contract__contract_number']
    readonly_fields = ['sign_token', 'signed_at', 'signed_name', 'signature_ip']


@admin.register(ContractAmendment)
class ContractAmendmentAdmin(admin.ModelAdmin):
    list_display = [
        'amendment_number', 'contract', 'change_type', 'status', 'applied_at',
    ]
    list_filter = ['tenant', 'status', 'change_type']
    search_fields = ['amendment_number', 'contract__contract_number', 'title']
    readonly_fields = ['amendment_number', 'prev_value', 'prev_end_date',
                       'applied_at', 'applied_by']

    def has_change_permission(self, request, obj=None):
        # Applied amendments are an immutable part of the version history.
        if obj is not None and obj.is_applied:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_applied:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(ContractObligation)
class ContractObligationAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'contract', 'obligation_type', 'due_date', 'amount', 'status',
    ]
    list_filter = ['tenant', 'obligation_type', 'status']
    search_fields = ['title', 'contract__contract_number']


@admin.register(ContractDocument)
class ContractDocumentAdmin(admin.ModelAdmin):
    list_display = ['contract', 'title', 'uploaded_by', 'uploaded_at']
    list_filter = ['tenant']
    search_fields = ['contract__contract_number', 'title']
    readonly_fields = ['uploaded_at']


@admin.register(ContractStatusEvent)
class ContractStatusEventAdmin(admin.ModelAdmin):
    list_display = ['contract', 'status', 'actor', 'created_at']
    list_filter = ['tenant', 'status']
    search_fields = ['contract__contract_number', 'note']
    readonly_fields = ['contract', 'status', 'note', 'actor', 'created_at']

    def has_add_permission(self, request):
        return False  # append-only

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False  # append-only

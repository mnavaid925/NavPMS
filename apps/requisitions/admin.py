from django.contrib import admin

from .models import (
    AccountCode, Requisition, RequisitionLine, RequisitionStatusEvent,
    RequisitionTemplate, RequisitionTemplateLine,
)


@admin.register(AccountCode)
class AccountCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'tenant', 'is_active')
    list_filter = ('is_active', 'tenant')
    search_fields = ('code', 'name')


class RequisitionTemplateLineInline(admin.TabularInline):
    model = RequisitionTemplateLine
    extra = 0


@admin.register(RequisitionTemplate)
class RequisitionTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'owner', 'category', 'is_shared')
    list_filter = ('category', 'is_shared', 'tenant')
    search_fields = ('name', 'owner__username')
    inlines = [RequisitionTemplateLineInline]


class RequisitionLineInline(admin.TabularInline):
    model = RequisitionLine
    extra = 0
    readonly_fields = ('line_total',)


class RequisitionStatusEventInline(admin.TabularInline):
    model = RequisitionStatusEvent
    extra = 0
    readonly_fields = ('from_status', 'to_status', 'changed_by', 'note', 'created_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Requisition)
class RequisitionAdmin(admin.ModelAdmin):
    list_display = ('number', 'tenant', 'title', 'requested_by', 'category',
                    'priority', 'status', 'revision', 'estimated_total',
                    'possible_duplicate', 'created_at')
    list_filter = ('status', 'category', 'priority', 'possible_duplicate', 'tenant')
    search_fields = ('number', 'title', 'requested_by__username', 'po_reference')
    inlines = [RequisitionLineInline, RequisitionStatusEventInline]


@admin.register(RequisitionLine)
class RequisitionLineAdmin(admin.ModelAdmin):
    list_display = ('description', 'requisition', 'quantity', 'unit',
                    'unit_price', 'line_total', 'account_code')
    search_fields = ('description', 'requisition__number')


@admin.register(RequisitionStatusEvent)
class RequisitionStatusEventAdmin(admin.ModelAdmin):
    list_display = ('requisition', 'from_status', 'to_status', 'changed_by', 'created_at')
    list_filter = ('to_status', 'tenant')
    search_fields = ('requisition__number',)

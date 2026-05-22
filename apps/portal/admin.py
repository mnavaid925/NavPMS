from django.contrib import admin

from .models import (
    DashboardWidget, Notification, QuickRequisition, QuickRequisitionItem,
    SavedReport,
)


@admin.register(DashboardWidget)
class DashboardWidgetAdmin(admin.ModelAdmin):
    list_display = ('title', 'tenant', 'user', 'widget_type', 'size',
                    'position', 'is_visible')
    list_filter = ('widget_type', 'size', 'is_visible', 'tenant')
    search_fields = ('title', 'user__username')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'tenant', 'user', 'category', 'priority',
                    'is_read', 'created_at')
    list_filter = ('category', 'priority', 'is_read', 'tenant')
    search_fields = ('title', 'message', 'user__username')


class QuickRequisitionItemInline(admin.TabularInline):
    model = QuickRequisitionItem
    extra = 0
    readonly_fields = ('line_total',)


@admin.register(QuickRequisition)
class QuickRequisitionAdmin(admin.ModelAdmin):
    list_display = ('number', 'tenant', 'user', 'title', 'category',
                    'priority', 'status', 'estimated_total', 'created_at')
    list_filter = ('status', 'category', 'priority', 'tenant')
    search_fields = ('number', 'title', 'vendor_name', 'user__username')
    inlines = [QuickRequisitionItemInline]


@admin.register(QuickRequisitionItem)
class QuickRequisitionItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'requisition', 'quantity', 'unit',
                    'unit_price', 'line_total')
    search_fields = ('name', 'requisition__number')


@admin.register(SavedReport)
class SavedReportAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'user', 'report_type',
                    'date_from', 'date_to', 'last_run_at')
    list_filter = ('report_type', 'tenant')
    search_fields = ('name', 'user__username')

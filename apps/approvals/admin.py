from django.contrib import admin

from .models import (
    ApprovalAction, ApprovalDelegation, ApprovalRequest, ApprovalRule,
    ApprovalStep, ApprovalTask,
)


class ApprovalStepInline(admin.TabularInline):
    model = ApprovalStep
    extra = 0


@admin.register(ApprovalRule)
class ApprovalRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'document_type', 'priority',
                    'min_amount', 'max_amount', 'department', 'category', 'is_active')
    list_filter = ('document_type', 'is_active', 'tenant')
    search_fields = ('name', 'department')
    inlines = [ApprovalStepInline]


@admin.register(ApprovalStep)
class ApprovalStepAdmin(admin.ModelAdmin):
    list_display = ('rule', 'order', 'name', 'approver', 'sla_hours', 'escalate_to')
    list_filter = ('tenant',)
    search_fields = ('name', 'rule__name')


@admin.register(ApprovalDelegation)
class ApprovalDelegationAdmin(admin.ModelAdmin):
    list_display = ('delegator', 'delegate', 'start_date', 'end_date', 'is_active')
    list_filter = ('is_active', 'tenant')
    search_fields = ('delegator__username', 'delegate__username')


class ApprovalTaskInline(admin.TabularInline):
    model = ApprovalTask
    extra = 0
    readonly_fields = ('step', 'order', 'name', 'assigned_to', 'original_approver',
                       'status', 'acted_by', 'acted_at', 'due_at', 'escalated_at')


class ApprovalActionInline(admin.TabularInline):
    model = ApprovalAction
    extra = 0
    readonly_fields = ('task', 'actor', 'action', 'comment', 'created_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ('requisition', 'tenant', 'rule', 'status',
                    'current_step', 'submitted_by', 'completed_at')
    list_filter = ('status', 'tenant')
    search_fields = ('requisition__number',)
    inlines = [ApprovalTaskInline, ApprovalActionInline]


@admin.register(ApprovalTask)
class ApprovalTaskAdmin(admin.ModelAdmin):
    list_display = ('name', 'request', 'order', 'assigned_to', 'status',
                    'due_at', 'acted_by', 'acted_at')
    list_filter = ('status', 'tenant')
    search_fields = ('name', 'request__requisition__number', 'assigned_to__username')


@admin.register(ApprovalAction)
class ApprovalActionAdmin(admin.ModelAdmin):
    list_display = ('request', 'action', 'actor', 'created_at')
    list_filter = ('action', 'tenant')
    search_fields = ('request__requisition__number', 'comment')
    readonly_fields = ('tenant', 'request', 'task', 'actor', 'action',
                       'comment', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

"""Admin registrations for Module 6: Sourcing & Tendering."""
from django.contrib import admin

from .models import (
    Bid, BidDocument, BidEvaluation, BidLine, SourcingAward,
    SourcingCriterion, SourcingEvent, SourcingEventInvitee, SourcingEventItem,
)


class SourcingEventItemInline(admin.TabularInline):
    model = SourcingEventItem
    extra = 0
    fields = ['line_no', 'item_description', 'uom', 'quantity', 'est_unit_price']


class SourcingCriterionInline(admin.TabularInline):
    model = SourcingCriterion
    extra = 0
    fields = ['order', 'name', 'criterion_type', 'weight', 'max_score']


class SourcingEventInviteeInline(admin.TabularInline):
    model = SourcingEventInvitee
    extra = 0
    fields = ['vendor', 'status', 'invited_at', 'responded_at']
    readonly_fields = ['invited_at', 'responded_at']


@admin.register(SourcingEvent)
class SourcingEventAdmin(admin.ModelAdmin):
    list_display = [
        'event_number', 'title', 'event_type', 'status', 'currency',
        'estimated_value', 'awarded_amount', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'event_type']
    search_fields = ['event_number', 'title', 'description']
    readonly_fields = [
        'event_number', 'awarded_vendor', 'awarded_amount', 'awarded_at',
        'cancelled_at', 'cancelled_by',
    ]
    inlines = [
        SourcingEventItemInline, SourcingCriterionInline, SourcingEventInviteeInline,
    ]


class BidLineInline(admin.TabularInline):
    model = BidLine
    extra = 0
    fields = ['event_item', 'unit_price', 'quantity_offered', 'lead_time_days']


class BidDocumentInline(admin.TabularInline):
    model = BidDocument
    extra = 0
    fields = ['title', 'file', 'uploaded_at']
    readonly_fields = ['uploaded_at']


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = [
        'bid_number', 'event', 'vendor', 'status', 'total_amount',
        'overall_score', 'rank', 'submitted_at',
    ]
    list_filter = ['tenant', 'status', 'is_compliant']
    search_fields = ['bid_number', 'vendor__legal_name', 'event__event_number']
    readonly_fields = ['bid_number', 'overall_score', 'rank', 'submitted_at']
    inlines = [BidLineInline, BidDocumentInline]


@admin.register(BidEvaluation)
class BidEvaluationAdmin(admin.ModelAdmin):
    list_display = ['bid', 'criterion', 'evaluator', 'score', 'evaluated_at']
    list_filter = ['tenant', 'criterion__event']
    search_fields = ['bid__bid_number', 'evaluator__username']


@admin.register(SourcingAward)
class SourcingAwardAdmin(admin.ModelAdmin):
    list_display = [
        'event', 'vendor', 'award_amount', 'currency', 'status',
        'awarded_by', 'awarded_at',
    ]
    list_filter = ['tenant', 'status']
    search_fields = ['event__event_number', 'vendor__legal_name']
    readonly_fields = ['awarded_at']

    def has_change_permission(self, request, obj=None):
        return False  # append-only

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SourcingEventItem)
class SourcingEventItemAdmin(admin.ModelAdmin):
    list_display = ['event', 'line_no', 'item_description', 'quantity', 'uom']
    search_fields = ['event__event_number', 'item_description']


@admin.register(SourcingCriterion)
class SourcingCriterionAdmin(admin.ModelAdmin):
    list_display = ['event', 'name', 'criterion_type', 'weight', 'max_score']
    list_filter = ['tenant', 'criterion_type']
    search_fields = ['event__event_number', 'name']


@admin.register(SourcingEventInvitee)
class SourcingEventInviteeAdmin(admin.ModelAdmin):
    list_display = ['event', 'vendor', 'status', 'invited_at', 'responded_at']
    list_filter = ['tenant', 'status']
    search_fields = ['vendor__legal_name', 'event__event_number']


@admin.register(BidLine)
class BidLineAdmin(admin.ModelAdmin):
    list_display = ['bid', 'event_item', 'unit_price', 'quantity_offered']
    search_fields = ['bid__bid_number']


@admin.register(BidDocument)
class BidDocumentAdmin(admin.ModelAdmin):
    list_display = ['bid', 'title', 'uploaded_at']
    search_fields = ['bid__bid_number', 'title']

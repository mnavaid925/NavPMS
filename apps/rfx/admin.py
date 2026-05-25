"""Admin registrations for Module 7: RFx Management."""
from django.contrib import admin

from .models import (
    RfxAnswer, RfxDocument, RfxEvaluation, RfxEvent, RfxInvitee,
    RfxQuestion, RfxResponse, RfxSection, RfxTemplate,
    RfxTemplateQuestion, RfxTemplateSection,
)


class RfxQuestionInline(admin.TabularInline):
    model = RfxQuestion
    extra = 0
    fields = [
        'position', 'prompt', 'question_type', 'is_required',
        'is_scored', 'weight', 'max_score',
    ]


@admin.register(RfxSection)
class RfxSectionAdmin(admin.ModelAdmin):
    list_display = ['event', 'position', 'title', 'tenant']
    list_filter = ['tenant']
    search_fields = ['title', 'event__event_number']
    inlines = [RfxQuestionInline]


class RfxSectionInline(admin.TabularInline):
    model = RfxSection
    extra = 0
    fields = ['position', 'title', 'description']
    show_change_link = True


class RfxInviteeInline(admin.TabularInline):
    model = RfxInvitee
    extra = 0
    fields = ['vendor', 'status', 'invited_at', 'responded_at']
    readonly_fields = ['invited_at']


class RfxDocumentInline(admin.TabularInline):
    model = RfxDocument
    extra = 0
    fields = ['title', 'file', 'uploaded_at']
    readonly_fields = ['uploaded_at']


@admin.register(RfxEvent)
class RfxEventAdmin(admin.ModelAdmin):
    list_display = [
        'event_number', 'title', 'rfx_type', 'status', 'currency', 'tenant',
    ]
    list_filter = ['tenant', 'status', 'rfx_type']
    search_fields = ['event_number', 'title', 'description']
    readonly_fields = [
        'event_number', 'completed_at', 'cancelled_at', 'cancelled_by',
    ]
    inlines = [RfxSectionInline, RfxInviteeInline, RfxDocumentInline]


class RfxAnswerInline(admin.TabularInline):
    model = RfxAnswer
    extra = 0
    fields = [
        'question', 'value_text', 'value_number', 'value_choices',
        'value_date', 'value_file',
    ]
    readonly_fields = ['question']


@admin.register(RfxResponse)
class RfxResponseAdmin(admin.ModelAdmin):
    list_display = [
        'event', 'vendor', 'status', 'overall_score', 'rank',
        'submitted_at', 'tenant',
    ]
    list_filter = ['tenant', 'status']
    search_fields = [
        'event__event_number', 'vendor__legal_name',
    ]
    readonly_fields = [
        'overall_score', 'rank', 'submitted_at', 'withdrawn_at',
    ]
    inlines = [RfxAnswerInline]


@admin.register(RfxEvaluation)
class RfxEvaluationAdmin(admin.ModelAdmin):
    list_display = ['response', 'question', 'evaluator', 'score', 'evaluated_at']
    list_filter = ['tenant']
    search_fields = ['response__vendor__legal_name', 'evaluator__username']


@admin.register(RfxInvitee)
class RfxInviteeAdmin(admin.ModelAdmin):
    list_display = ['event', 'vendor', 'status', 'invited_at', 'responded_at']
    list_filter = ['tenant', 'status']
    search_fields = ['vendor__legal_name', 'event__event_number']


@admin.register(RfxDocument)
class RfxDocumentAdmin(admin.ModelAdmin):
    list_display = ['event', 'title', 'uploaded_by', 'uploaded_at']
    search_fields = ['title', 'event__event_number']


@admin.register(RfxQuestion)
class RfxQuestionAdmin(admin.ModelAdmin):
    list_display = ['section', 'position', 'prompt', 'question_type', 'weight']
    list_filter = ['tenant', 'question_type', 'is_scored']
    search_fields = ['prompt', 'section__title']


@admin.register(RfxAnswer)
class RfxAnswerAdmin(admin.ModelAdmin):
    list_display = ['response', 'question']
    search_fields = ['response__vendor__legal_name', 'question__prompt']


class RfxTemplateQuestionInline(admin.TabularInline):
    model = RfxTemplateQuestion
    extra = 0
    fields = [
        'position', 'prompt', 'question_type', 'is_required',
        'is_scored', 'weight', 'max_score',
    ]


@admin.register(RfxTemplateSection)
class RfxTemplateSectionAdmin(admin.ModelAdmin):
    list_display = ['template', 'position', 'title']
    search_fields = ['title', 'template__title']
    inlines = [RfxTemplateQuestionInline]


class RfxTemplateSectionInline(admin.TabularInline):
    model = RfxTemplateSection
    extra = 0
    fields = ['position', 'title', 'description']
    show_change_link = True


@admin.register(RfxTemplate)
class RfxTemplateAdmin(admin.ModelAdmin):
    list_display = ['title', 'rfx_type', 'is_shared', 'archived', 'tenant']
    list_filter = ['tenant', 'rfx_type', 'is_shared', 'archived']
    search_fields = ['title', 'description']
    inlines = [RfxTemplateSectionInline]


@admin.register(RfxTemplateQuestion)
class RfxTemplateQuestionAdmin(admin.ModelAdmin):
    list_display = ['section', 'position', 'prompt', 'question_type', 'weight']
    list_filter = ['tenant', 'question_type', 'is_scored']
    search_fields = ['prompt', 'section__title']

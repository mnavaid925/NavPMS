"""Module 7 forms: events, sections, questions, invitees, documents,
shortlist/reject decisions, templates and template clone."""
import os
from decimal import Decimal

from django import forms

from apps.vendors.models import Vendor, VendorCategory

from .models import (
    CHOICE_QUESTION_TYPES,
    RfxDocument,
    RfxEvent,
    RfxQuestion,
    RfxSection,
    RfxTemplate,
    RfxTemplateQuestion,
    RfxTemplateSection,
)


# ---------- Helpers ----------

def _choices_to_text(choices):
    """JSON list -> textarea string (one choice per line)."""
    if not choices:
        return ''
    return '\n'.join(str(c) for c in choices)


def _text_to_choices(raw):
    """Textarea string -> list of trimmed non-empty choices."""
    if not raw:
        return []
    return [line.strip() for line in str(raw).splitlines() if line.strip()]


# ---------- Event ----------

class RfxEventForm(forms.ModelForm):
    class Meta:
        model = RfxEvent
        fields = [
            'title', 'description', 'rfx_type', 'category', 'currency',
            'publish_at', 'close_at', 'terms_and_conditions',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'terms_and_conditions': forms.Textarea(attrs={'rows': 4}),
            'publish_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'close_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant is not None:
            self.fields['category'].queryset = VendorCategory.objects.filter(
                tenant=tenant, is_active=True,
            )

    def clean(self):
        cleaned = super().clean()
        publish = cleaned.get('publish_at')
        close = cleaned.get('close_at')
        if publish and close and close <= publish:
            raise forms.ValidationError('Close date must be after publish date.')
        return cleaned


# ---------- Section ----------

class RfxSectionForm(forms.ModelForm):
    class Meta:
        model = RfxSection
        fields = ['title', 'description', 'position']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'position': forms.NumberInput(attrs={'min': 1, 'step': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['position'].required = False
        self.fields['position'].help_text = 'Leave blank to append at the end.'


# ---------- Question (event-scoped) ----------

class _BaseQuestionForm(forms.ModelForm):
    """Shared form logic for RfxQuestion + RfxTemplateQuestion."""

    choices_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'One choice per line (only for single/multi choice questions)',
        }),
        help_text='One choice per line — required for single_choice / multi_choice; ignored otherwise.',
        label='Choices',
    )

    class Meta:
        fields = [
            'prompt', 'help_text', 'question_type', 'is_required',
            'is_scored', 'weight', 'max_score', 'position',
        ]
        widgets = {
            'help_text': forms.Textarea(attrs={'rows': 2}),
            'weight': forms.NumberInput(attrs={'min': 0, 'max': 100, 'step': '0.01'}),
            'max_score': forms.NumberInput(attrs={'min': 1, 'step': 1}),
            'position': forms.NumberInput(attrs={'min': 1, 'step': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['position'].required = False
        self.fields['position'].help_text = 'Leave blank to append at the end.'
        if self.instance and self.instance.pk:
            self.fields['choices_text'].initial = _choices_to_text(
                self.instance.choices or [],
            )

    def clean(self):
        cleaned = super().clean()
        qtype = cleaned.get('question_type')
        is_scored = cleaned.get('is_scored')
        weight = cleaned.get('weight') or Decimal('0')
        choices = _text_to_choices(cleaned.get('choices_text'))
        cleaned['choices'] = choices
        if qtype in CHOICE_QUESTION_TYPES and len(choices) < 2:
            raise forms.ValidationError(
                'Choice-type questions need at least 2 options (one per line).'
            )
        if is_scored and weight <= Decimal('0'):
            raise forms.ValidationError(
                'Scored questions need a weight greater than 0.'
            )
        if not is_scored and weight > Decimal('0'):
            # Allow it but warn via a non-blocking message? For now: enforce 0.
            cleaned['weight'] = Decimal('0')
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.choices = self.cleaned_data.get('choices') or []
        if commit:
            obj.save()
        return obj


class RfxQuestionForm(_BaseQuestionForm):
    class Meta(_BaseQuestionForm.Meta):
        model = RfxQuestion


class RfxTemplateQuestionForm(_BaseQuestionForm):
    class Meta(_BaseQuestionForm.Meta):
        model = RfxTemplateQuestion


# ---------- Template section ----------

class RfxTemplateSectionForm(forms.ModelForm):
    class Meta:
        model = RfxTemplateSection
        fields = ['title', 'description', 'position']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'position': forms.NumberInput(attrs={'min': 1, 'step': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['position'].required = False
        self.fields['position'].help_text = 'Leave blank to append at the end.'


# ---------- Invitees ----------

class InviteVendorsForm(forms.Form):
    vendors = forms.ModelMultipleChoiceField(
        queryset=Vendor.objects.none(),
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, tenant=None, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant is None:
            return
        existing = (
            event.invitees.values_list('vendor_id', flat=True)
            if event else []
        )
        qs = Vendor.objects.filter(
            tenant=tenant,
        ).exclude(
            status__in=('suspended', 'blacklisted', 'inactive'),
        ).exclude(pk__in=existing).order_by('legal_name')
        self.fields['vendors'].queryset = qs


# ---------- Document ----------

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MB — buyer brief / spec sheets
MAX_ANSWER_FILE_BYTES = 5 * 1024 * 1024  # 5 MB — vendor per-answer uploads

# Extension allow-list for both buyer documents and vendor answer files
# (SQA defect D-04). Whitelist, not blacklist: anything not listed — notably
# .svg / .html / .htm / .js / .exe — is rejected, since MEDIA may be served
# inline by Apache in production and active content would be stored XSS.
ALLOWED_UPLOAD_EXTENSIONS = frozenset({
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.csv', '.txt', '.png', '.jpg', '.jpeg', '.gif', '.zip',
})


def upload_error(f, max_bytes):
    """Validate an uploaded file; return an error message, or '' if acceptable.

    Used both by ``RfxDocumentForm.clean_file`` (which re-raises) and by the
    vendor-portal answer handler (which collects message strings).
    """
    if not f:
        return ''
    if f.size > max_bytes:
        return f'File size must be {max_bytes // (1024 * 1024)} MB or less.'
    ext = os.path.splitext((f.name or '').lower())[1]
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return (
            f'File type "{ext or "unknown"}" is not allowed. '
            f'Permitted: {", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}.'
        )
    return ''


class RfxDocumentForm(forms.ModelForm):
    class Meta:
        model = RfxDocument
        fields = ['title', 'file', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}

    def clean_file(self):
        f = self.cleaned_data.get('file')
        err = upload_error(f, MAX_DOCUMENT_BYTES)
        if err:
            raise forms.ValidationError(err)
        return f


# ---------- Cancel / decision reasons ----------

class CancelEventForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'placeholder': 'Why are you cancelling this event?',
        }),
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason


class ResponseDecisionForm(forms.Form):
    """Captures an optional reason on shortlist / reject."""

    reason = forms.CharField(
        max_length=255, required=False,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'placeholder': 'Optional note (visible to other evaluators).',
        }),
    )


# ---------- Templates ----------

class RfxTemplateForm(forms.ModelForm):
    class Meta:
        model = RfxTemplate
        fields = ['title', 'description', 'rfx_type', 'is_shared']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class UseTemplateForm(forms.Form):
    """Used when creating an event from a template."""

    title = forms.CharField(max_length=200)
    publish_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )
    close_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )

    def clean(self):
        cleaned = super().clean()
        publish = cleaned.get('publish_at')
        close = cleaned.get('close_at')
        if publish and close and close <= publish:
            raise forms.ValidationError('Close date must be after publish date.')
        return cleaned


class SaveAsTemplateForm(forms.Form):
    """Snapshot an event's questionnaire into a new template."""

    title = forms.CharField(max_length=200)
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
    )
    is_shared = forms.BooleanField(required=False, initial=True)

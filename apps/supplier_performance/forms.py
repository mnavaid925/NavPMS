"""Module 17 forms: KPI definition, scorecard generation, 360° feedback, and PIP.

A ``tenant=`` kwarg scopes every FK dropdown (vendor, reviewer, owner, scorecard) to the current
tenant, mirroring the budget / goods_receipt style.
"""
from django import forms

from apps.accounts.models import User
from apps.vendors.models import Vendor

from .models import (
    ImprovementPlan, KpiDefinition, PerformanceFeedback, PIPAction, Scorecard,
)


class KpiDefinitionForm(forms.ModelForm):
    class Meta:
        model = KpiDefinition
        fields = [
            'code', 'name', 'description', 'kpi_type', 'source', 'direction', 'weight',
            'target_value', 'unit', 'green_threshold', 'amber_threshold', 'is_active',
            'display_order',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['description'].required = False
        self.fields['target_value'].required = False
        self.fields['unit'].required = False
        self.fields['code'].help_text = 'Stable key, e.g. OTD. Unique within your organisation.'

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip().upper()
        if self.tenant is not None and code:
            qs = KpiDefinition.all_objects.filter(tenant=self.tenant, code=code)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('A KPI with this code already exists.')
        return code


class ScorecardGenerateForm(forms.Form):
    """Pick a vendor + a period; the engine fills the lines."""

    vendor = forms.ModelChoiceField(queryset=Vendor.objects.none())
    period_label = forms.CharField(max_length=40, required=False,
                                    help_text='e.g. "Q1 2026" (defaults to the date range).')
    period_start = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    period_end = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    finalize = forms.BooleanField(
        required=False, initial=True,
        help_text='Finalize immediately (updates the vendor score). Uncheck to keep as draft.')

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant is not None:
            self.fields['vendor'].queryset = (
                Vendor.objects.filter(tenant=tenant, status='active').order_by('legal_name'))

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('period_start'), cleaned.get('period_end')
        if start and end and end < start:
            self.add_error('period_end', 'Period end must not be before the start.')
        return cleaned


class FeedbackRequestForm(forms.Form):
    """Request 360° feedback from an internal stakeholder about a vendor."""

    vendor = forms.ModelChoiceField(queryset=Vendor.objects.none())
    reviewer = forms.ModelChoiceField(queryset=User.objects.none())
    period_label = forms.CharField(max_length=40, required=False)

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant is not None:
            self.fields['vendor'].queryset = (
                Vendor.objects.filter(tenant=tenant, status='active').order_by('legal_name'))
            self.fields['reviewer'].queryset = (
                User.objects.filter(tenant=tenant, is_active=True, vendor__isnull=True)
                .order_by('username'))


class FeedbackSubmitForm(forms.ModelForm):
    class Meta:
        model = PerformanceFeedback
        fields = [
            'rating', 'quality_rating', 'delivery_rating', 'communication_rating',
            'would_recommend', 'comments',
        ]
        widgets = {
            'comments': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rating'].required = True
        for name in ('quality_rating', 'delivery_rating', 'communication_rating'):
            self.fields[name].required = False
        self.fields['would_recommend'].required = False
        self.fields['comments'].required = False


class ImprovementPlanForm(forms.ModelForm):
    class Meta:
        model = ImprovementPlan
        fields = ['vendor', 'scorecard', 'title', 'summary', 'severity', 'owner', 'target_date']
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 3}),
            'target_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['summary'].required = False
        self.fields['scorecard'].required = False
        self.fields['owner'].required = False
        self.fields['target_date'].required = False
        if tenant is not None:
            self.fields['vendor'].queryset = (
                Vendor.objects.filter(tenant=tenant).order_by('legal_name'))
            self.fields['scorecard'].queryset = (
                Scorecard.objects.filter(tenant=tenant, status='final').order_by('-period_end'))
            self.fields['owner'].queryset = (
                User.objects.filter(tenant=tenant, is_active=True, vendor__isnull=True)
                .order_by('username'))


class PIPActionForm(forms.ModelForm):
    class Meta:
        model = PIPAction
        fields = ['description', 'status', 'due_date', 'assigned_to', 'notes', 'line_no']
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.TextInput(),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['due_date'].required = False
        self.fields['assigned_to'].required = False
        self.fields['notes'].required = False
        self.fields['line_no'].required = False
        if tenant is not None:
            self.fields['assigned_to'].queryset = (
                User.objects.filter(tenant=tenant, is_active=True, vendor__isnull=True)
                .order_by('username'))

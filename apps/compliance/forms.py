"""Module 18 forms: screening, restricted-party entries, fraud rules, policies, financial monitoring.

A ``tenant=`` kwarg scopes every FK dropdown to the current tenant (vendors, owners), mirroring the
budget / goods_receipt style.
"""
from django import forms

from apps.accounts.models import User
from apps.vendors.models import Vendor

from .models import (
    FraudRule, Policy, PolicyVersion, RestrictedPartyEntry,
)


class RestrictedPartyEntryForm(forms.ModelForm):
    class Meta:
        model = RestrictedPartyEntry
        fields = ['list_name', 'entity_name', 'entry_type', 'country', 'program',
                  'source_ref', 'is_active']
        widgets = {
            'program': forms.TextInput(),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        for name in ('country', 'program', 'source_ref'):
            self.fields[name].required = False
        self.fields['list_name'].help_text = 'e.g. OFAC-SDN, SAM-EPLS, EU-CFSP.'


class ScreeningRunForm(forms.Form):
    """Run an ad-hoc or vendor screening. Provide a vendor OR a free-text name."""
    vendor = forms.ModelChoiceField(queryset=Vendor.objects.none(), required=False,
                                    label='Vendor')
    screened_name = forms.CharField(max_length=200, required=False, label='Or name to screen')

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant is not None:
            self.fields['vendor'].queryset = Vendor.objects.filter(
                tenant=tenant).order_by('legal_name')

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('vendor') and not (cleaned.get('screened_name') or '').strip():
            raise forms.ValidationError('Select a vendor or enter a name to screen.')
        return cleaned


class FinancialMonitorForm(forms.Form):
    """Add a vendor to financial-risk monitoring (creates/refreshes its profile)."""
    vendor = forms.ModelChoiceField(queryset=Vendor.objects.none(), label='Vendor')

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant is not None:
            self.fields['vendor'].queryset = Vendor.objects.filter(
                tenant=tenant).order_by('legal_name')


class FraudRuleForm(forms.ModelForm):
    class Meta:
        model = FraudRule
        fields = ['code', 'name', 'description', 'severity', 'is_active', 'display_order']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['description'].required = False
        self.fields['display_order'].required = False


class PolicyForm(forms.ModelForm):
    class Meta:
        model = Policy
        fields = ['title', 'category', 'summary', 'owner', 'requires_acknowledgment']
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['summary'].required = False
        self.fields['owner'].required = False
        if tenant is not None:
            self.fields['owner'].queryset = User.objects.filter(
                tenant=tenant, is_active=True).order_by('username')
        self.fields['owner'].label = 'Policy owner'


class PolicyVersionForm(forms.ModelForm):
    publish = forms.BooleanField(
        required=False, label='Publish this version now',
        help_text='Make it the current version and ask users to acknowledge.')

    class Meta:
        model = PolicyVersion
        fields = ['body', 'change_note', 'effective_date']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 10}),
            'effective_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['change_note'].required = False
        self.fields['effective_date'].required = False

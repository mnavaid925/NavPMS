"""Module 15 forms: the Custom Report Builder definition form.

Mirrors the goods_receipt/invoicing style — a ``tenant=`` kwarg scopes the FK dropdowns to the
current tenant, ``date`` widgets drive the date window, and optional/defaulted fields are made
``required=False`` (a model default does not make a ModelForm field optional). ``SpendReport`` has
no tenant-scoped ``unique_together`` so there is no uniqueness ``clean_<field>`` to add.
"""
from django import forms

from apps.requisitions.models import AccountCode
from apps.vendors.models import Vendor, VendorCategory, VendorSegment

from .models import SpendReport


class SpendReportForm(forms.ModelForm):
    class Meta:
        model = SpendReport
        fields = [
            'name', 'description', 'dimension', 'measure', 'chart_type', 'basis',
            'date_from', 'date_to', 'vendor', 'vendor_category', 'vendor_segment',
            'account_code', 'source_type', 'maverick_only', 'is_shared',
        ]
        widgets = {
            'date_from': forms.DateInput(attrs={'type': 'date'}),
            'date_to': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.TextInput(),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        for f in (
            'description', 'date_from', 'date_to', 'vendor', 'vendor_category',
            'vendor_segment', 'account_code', 'source_type', 'maverick_only', 'is_shared',
        ):
            self.fields[f].required = False
        if tenant is not None:
            self.fields['vendor'].queryset = (
                Vendor.objects.filter(tenant=tenant).order_by('legal_name'))
            self.fields['vendor_category'].queryset = (
                VendorCategory.objects.filter(tenant=tenant).order_by('name'))
            self.fields['vendor_segment'].queryset = (
                VendorSegment.objects.filter(tenant=tenant).order_by('name'))
            self.fields['account_code'].queryset = (
                AccountCode.objects.filter(tenant=tenant).order_by('code'))
        self.fields['account_code'].label = 'Cost Center / Account Code'
        self.fields['source_type'].label = 'Source'

    def clean(self):
        cleaned = super().clean()
        df, dt = cleaned.get('date_from'), cleaned.get('date_to')
        if df and dt and df > dt:
            self.add_error('date_to', 'End date must not be before the start date.')
        return cleaned

"""Module 10 forms: catalog items, categories, price tiers, price-change
requests, punch-out configuration and supplier uploads.

Mirrors the contracts form style: a ``tenant=`` kwarg scopes FK dropdowns to the
current tenant, ``date`` widgets drive effective-date fields, and lightweight
``forms.Form`` classes back the lifecycle actions. The punch-out shared secret is
write-only (never rendered back) and the setup URL is SSRF-validated.
"""
from django import forms

from apps.vendors.models import Vendor

from . import services
from .models import (
    CatalogCategory,
    CatalogItem,
    CatalogPriceChangeRequest,
    CatalogPriceTier,
    SupplierCatalogUpload,
    SupplierPunchoutConfig,
)


# ---------- Catalog item ----------

class CatalogItemForm(forms.ModelForm):
    class Meta:
        model = CatalogItem
        fields = [
            'name', 'description', 'sku', 'manufacturer_part_number', 'keywords',
            'source', 'category', 'vendor', 'account_code', 'uom', 'currency',
            'base_price', 'min_order_qty', 'lead_time_days', 'image', 'is_active',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'keywords': forms.TextInput(attrs={'placeholder': 'comma, separated, terms'}),
            'base_price': forms.NumberInput(attrs={'min': 0, 'step': '0.0001'}),
            'min_order_qty': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'lead_time_days': forms.NumberInput(attrs={'min': 0, 'step': 1}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['category'].required = False
        self.fields['vendor'].required = False
        self.fields['account_code'].required = False
        if tenant is not None:
            from apps.requisitions.models import AccountCode
            self.fields['category'].queryset = CatalogCategory.objects.filter(
                tenant=tenant, is_active=True)
            self.fields['vendor'].queryset = Vendor.objects.filter(
                tenant=tenant,
            ).exclude(
                status__in=('suspended', 'blacklisted', 'inactive'),
            ).order_by('legal_name')
            self.fields['account_code'].queryset = AccountCode.objects.filter(
                tenant=tenant, is_active=True)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('source') == 'supplier' and not cleaned.get('vendor'):
            self.add_error('vendor', 'Choose a supplier for a supplier-sourced item.')
        return cleaned


# ---------- Category ----------

class CatalogCategoryForm(forms.ModelForm):
    class Meta:
        model = CatalogCategory
        fields = ['name', 'code', 'description', 'parent', 'is_active']
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parent'].required = False
        if tenant is not None:
            qs = CatalogCategory.objects.filter(tenant=tenant)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            self.fields['parent'].queryset = qs


# ---------- Price tier ----------

class CatalogPriceTierForm(forms.ModelForm):
    class Meta:
        model = CatalogPriceTier
        fields = [
            'tier_type', 'min_quantity', 'unit_price', 'contract',
            'effective_from', 'effective_to', 'is_active',
        ]
        widgets = {
            'min_quantity': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'unit_price': forms.NumberInput(attrs={'min': 0, 'step': '0.0001'}),
            'effective_from': forms.DateInput(attrs={'type': 'date'}),
            'effective_to': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, tenant=None, item=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.item = item
        self.fields['contract'].required = False
        if tenant is not None:
            from apps.contracts.models import Contract
            self.fields['contract'].queryset = Contract.objects.filter(tenant=tenant)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('effective_from')
        end = cleaned.get('effective_to')
        if start and end and end < start:
            self.add_error('effective_to', 'End date must be on or after the start date.')
        if cleaned.get('tier_type') == 'contract' and not cleaned.get('contract'):
            self.add_error('contract', 'Select the contract this price comes from.')
        return cleaned


# ---------- Price-change request ----------

class CatalogPriceChangeForm(forms.ModelForm):
    class Meta:
        model = CatalogPriceChangeRequest
        fields = ['change_type', 'new_base_price', 'reason', 'effective_date']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 2}),
            'new_base_price': forms.NumberInput(attrs={'min': 0, 'step': '0.0001'}),
            'effective_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        cleaned = super().clean()
        change_type = cleaned.get('change_type')
        if change_type in ('base', 'both') and cleaned.get('new_base_price') is None:
            self.add_error('new_base_price', 'Enter the proposed base price.')
        return cleaned


# ---------- Punch-out configuration ----------

class SupplierPunchoutConfigForm(forms.ModelForm):
    # WARNING: write-only — the stored secret is never rendered back to the page.
    shared_secret = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        help_text='Leave blank to keep the current secret.',
    )

    class Meta:
        model = SupplierPunchoutConfig
        fields = [
            'vendor', 'name', 'protocol', 'setup_url', 'from_identity',
            'to_identity', 'sender_identity', 'shared_secret', 'username',
            'extra_params', 'is_active',
        ]
        widgets = {
            'setup_url': forms.URLInput(attrs={'placeholder': 'https://supplier.example.com/punchout'}),
            'extra_params': forms.Textarea(attrs={'rows': 2, 'placeholder': '{"OCI_VERSION": "4.0"}'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant is not None:
            self.fields['vendor'].queryset = Vendor.objects.filter(
                tenant=tenant).order_by('legal_name')

    def clean_setup_url(self):
        url = self.cleaned_data.get('setup_url')
        if url:
            services.validate_punchout_url(url)  # raises ValidationError on SSRF
        return url

    def clean_shared_secret(self):
        secret = self.cleaned_data.get('shared_secret')
        if not secret and self.instance and self.instance.pk:
            return self.instance.shared_secret  # blank = keep existing
        return secret


# ---------- Supplier upload ----------

class SupplierCatalogUploadForm(forms.ModelForm):
    class Meta:
        model = SupplierCatalogUpload
        fields = ['file', 'category']

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].required = False
        if tenant is not None:
            self.fields['category'].queryset = CatalogCategory.objects.filter(
                tenant=tenant, is_active=True)


# ---------- Lifecycle action forms ----------

class RejectForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Reason for rejection'}),
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason


class RetireForm(forms.Form):
    reason = forms.CharField(
        max_length=255, required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Why retire this item? (optional)'}),
    )

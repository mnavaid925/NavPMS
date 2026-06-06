"""Module 16 forms: budget period, budget header, and allocation line.

A ``tenant=`` kwarg scopes every FK dropdown to the current tenant (periods, owner, account codes,
vendor categories), mirroring the goods_receipt / spend_analytics style.
"""
from django import forms

from apps.accounts.models import User
from apps.requisitions.models import AccountCode
from apps.vendors.models import VendorCategory

from .models import Budget, BudgetAllocation, BudgetPeriod


class BudgetPeriodForm(forms.ModelForm):
    class Meta:
        model = BudgetPeriod
        fields = ['name', 'period_type', 'start_date', 'end_date', 'status', 'is_default', 'notes']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['notes'].required = False
        self.fields['is_default'].required = False

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('start_date'), cleaned.get('end_date')
        if start and end and start > end:
            self.add_error('end_date', 'End date must not be before the start date.')
        return cleaned


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ['name', 'description', 'period', 'currency', 'owner']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['description'].required = False
        self.fields['owner'].required = False
        if tenant is not None:
            self.fields['period'].queryset = (
                BudgetPeriod.objects.filter(tenant=tenant).order_by('-start_date'))
            self.fields['owner'].queryset = (
                User.objects.filter(tenant=tenant, is_active=True).order_by('username'))
        self.fields['owner'].label = 'Budget owner'


class BudgetAllocationForm(forms.ModelForm):
    class Meta:
        model = BudgetAllocation
        fields = ['account_code', 'vendor_category', 'allocated_amount', 'line_no', 'notes']
        widgets = {
            'notes': forms.TextInput(),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['vendor_category'].required = False
        self.fields['notes'].required = False
        self.fields['line_no'].required = False
        if tenant is not None:
            self.fields['account_code'].queryset = (
                AccountCode.objects.filter(tenant=tenant, is_active=True).order_by('code'))
            self.fields['vendor_category'].queryset = (
                VendorCategory.objects.filter(tenant=tenant).order_by('name'))
        self.fields['account_code'].label = 'Cost Center / Account Code'
        self.fields['vendor_category'].label = 'Category (optional)'

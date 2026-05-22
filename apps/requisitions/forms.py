"""Forms for Module 3 (account codes, templates, requisitions, lines)."""
from django import forms

from .models import (
    AccountCode, Requisition, RequisitionLine, RequisitionTemplate,
    RequisitionTemplateLine,
)


class AccountCodeForm(forms.ModelForm):
    class Meta:
        model = AccountCode
        fields = ('code', 'name', 'description', 'is_active')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }


class RequisitionTemplateForm(forms.ModelForm):
    class Meta:
        model = RequisitionTemplate
        fields = ('name', 'description', 'category', 'default_account_code', 'is_shared')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['default_account_code'].queryset = (
            AccountCode.objects.filter(is_active=True)
        )


class RequisitionTemplateLineForm(forms.ModelForm):
    """Rendered field-by-field on the template detail page."""

    class Meta:
        model = RequisitionTemplateLine
        fields = ('description', 'quantity', 'unit', 'estimated_unit_price',
                  'account_code')
        widgets = {
            'description': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Item description',
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'step': '0.01',
            }),
            'unit': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'unit'}),
            'estimated_unit_price': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'step': '0.01',
            }),
            'account_code': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account_code'].queryset = (
            AccountCode.objects.filter(is_active=True)
        )
        self.fields['account_code'].required = False


class RequisitionForm(forms.ModelForm):
    class Meta:
        model = Requisition
        fields = ('title', 'category', 'department', 'priority',
                  'required_date', 'justification', 'notes', 'currency')
        widgets = {
            'required_date': forms.DateInput(attrs={'type': 'date'}),
            'justification': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class RequisitionLineForm(forms.ModelForm):
    """Rendered field-by-field on the requisition detail page."""

    class Meta:
        model = RequisitionLine
        fields = ('description', 'quantity', 'unit', 'unit_price',
                  'account_code', 'required_date')
        widgets = {
            'description': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Item description',
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'step': '0.01',
            }),
            'unit': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'unit'}),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'step': '0.01',
            }),
            'account_code': forms.Select(attrs={'class': 'form-select'}),
            'required_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account_code'].queryset = (
            AccountCode.objects.filter(is_active=True)
        )
        self.fields['account_code'].required = False
        self.fields['required_date'].required = False

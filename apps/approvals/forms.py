"""Forms for Module 4 (rules, steps, delegations)."""
from django import forms

from apps.accounts.models import User
from apps.requisitions.models import CATEGORY_CHOICES

from .models import ApprovalDelegation, ApprovalRule, ApprovalStep


class ApprovalRuleForm(forms.ModelForm):
    category = forms.ChoiceField(
        choices=[('', 'Any category')] + list(CATEGORY_CHOICES),
        required=False,
    )

    class Meta:
        model = ApprovalRule
        fields = ('name', 'document_type', 'description', 'is_active',
                  'priority', 'min_amount', 'max_amount', 'department', 'category')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'department': forms.TextInput(attrs={'placeholder': 'Blank = any department'}),
        }


class ApprovalStepForm(forms.ModelForm):
    """Rendered field-by-field on the rule detail page."""

    class Meta:
        model = ApprovalStep
        fields = ('order', 'name', 'approver', 'sla_hours', 'escalate_to')
        widgets = {
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'e.g. Manager review',
            }),
            'approver': forms.Select(attrs={'class': 'form-select'}),
            'sla_hours': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'escalate_to': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        users = User.objects.filter(is_active=True)
        if tenant is not None:
            users = users.filter(tenant=tenant)
        self.fields['approver'].queryset = users
        self.fields['escalate_to'].queryset = users
        self.fields['escalate_to'].required = False


class ApprovalDelegationForm(forms.ModelForm):
    class Meta:
        model = ApprovalDelegation
        fields = ('delegate', 'start_date', 'end_date', 'reason', 'is_active')
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.TextInput(attrs={'placeholder': 'Reason for delegation'}),
        }

    def __init__(self, *args, tenant=None, exclude_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        users = User.objects.filter(is_active=True)
        if tenant is not None:
            users = users.filter(tenant=tenant)
        if exclude_user is not None:
            users = users.exclude(pk=exclude_user.pk)
        self.fields['delegate'].queryset = users

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('start_date'), cleaned.get('end_date')
        if start and end and end < start:
            self.add_error('end_date', 'End date cannot be before the start date.')
        return cleaned

"""Module 9 forms: contract authoring, clauses, templates, signatories,
amendments, obligations, documents and the lifecycle actions.

Mirrors the auctions form style: a ``tenant=`` kwarg scopes FK dropdowns
(category / vendor / account_code) to the current tenant, ``date`` widgets drive
the term fields, and lightweight ``forms.Form`` classes back the lifecycle
actions (sign / decline / terminate / cancel / save-as-template).
"""
from django import forms

from apps.vendors.models import Vendor

from .models import (
    Contract,
    ContractAmendment,
    ContractClause,
    ContractClauseLine,
    ContractDocument,
    ContractObligation,
    ContractSignatory,
    ContractTemplate,
)


# ---------- Contract ----------

class ContractForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = [
            'title', 'description', 'contract_type', 'category', 'vendor',
            'currency', 'value', 'start_date', 'end_date', 'auto_renew',
            'renewal_term_months', 'renewal_notice_days', 'owner',
            'sourcing_event', 'requisition', 'terms_and_conditions',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'terms_and_conditions': forms.Textarea(attrs={'rows': 4}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'value': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'renewal_term_months': forms.NumberInput(attrs={'min': 1, 'step': 1}),
            'renewal_notice_days': forms.NumberInput(attrs={'min': 0, 'step': 1}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant is not None:
            from apps.requisitions.models import Requisition
            from apps.sourcing.models import SourcingEvent
            from apps.vendors.models import VendorCategory

            self.fields['category'].queryset = VendorCategory.objects.filter(
                tenant=tenant, is_active=True,
            )
            self.fields['vendor'].queryset = Vendor.objects.filter(
                tenant=tenant,
            ).exclude(
                status__in=('suspended', 'blacklisted', 'inactive'),
            ).order_by('legal_name')
            self.fields['owner'].queryset = self.fields['owner'].queryset.filter(
                tenant=tenant, is_active=True,
            )
            self.fields['sourcing_event'].queryset = SourcingEvent.objects.filter(
                tenant=tenant,
            )
            self.fields['sourcing_event'].required = False
            self.fields['requisition'].queryset = Requisition.objects.filter(
                tenant=tenant,
            )
            self.fields['requisition'].required = False
            self.fields['category'].required = False
            self.fields['owner'].required = False

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and end <= start:
            self.add_error('end_date', 'End date must be after the start date.')
        return cleaned


# ---------- Clause line (authored onto a contract) ----------

class ContractClauseLineForm(forms.ModelForm):
    class Meta:
        model = ContractClauseLine
        fields = ['heading', 'body', 'sort_order']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 5}),
            'sort_order': forms.NumberInput(attrs={'min': 1, 'step': 1}),
        }

    def __init__(self, *args, contract=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = contract

    def clean_sort_order(self):
        order = self.cleaned_data.get('sort_order') or 1
        if self.contract:
            qs = ContractClauseLine.all_objects.filter(
                contract=self.contract, sort_order=order,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f'Position {order} already exists on this contract.')
        return order


class AddClauseFromLibraryForm(forms.Form):
    clause = forms.ModelChoiceField(queryset=ContractClause.objects.none())

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant is not None:
            self.fields['clause'].queryset = ContractClause.objects.filter(
                tenant=tenant, is_active=True,
            )


# ---------- Clause library ----------

class ContractClauseForm(forms.ModelForm):
    class Meta:
        model = ContractClause
        fields = ['title', 'category', 'body', 'is_standard', 'is_active', 'sort_order']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 6}),
            'sort_order': forms.NumberInput(attrs={'min': 0, 'step': 1}),
        }


# ---------- Templates ----------

class ContractTemplateForm(forms.ModelForm):
    class Meta:
        model = ContractTemplate
        fields = ['title', 'description', 'contract_type', 'is_shared', 'archived']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}


# ---------- Signatory ----------

class SignatoryForm(forms.ModelForm):
    class Meta:
        model = ContractSignatory
        fields = ['party', 'name', 'email', 'title', 'order', 'user', 'vendor']
        widgets = {'order': forms.NumberInput(attrs={'min': 1, 'step': 1})}

    def __init__(self, *args, tenant=None, contract=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.contract = contract
        self.fields['user'].required = False
        self.fields['vendor'].required = False
        self.fields['email'].required = False
        if tenant is not None:
            self.fields['user'].queryset = self.fields['user'].queryset.filter(
                tenant=tenant, is_active=True,
            )
            self.fields['vendor'].queryset = Vendor.objects.filter(tenant=tenant)

    def clean_order(self):
        order = self.cleaned_data.get('order') or 1
        if self.contract:
            qs = ContractSignatory.all_objects.filter(
                contract=self.contract, order=order,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f'Signing order {order} is already used on this contract.')
        return order


class SignForm(forms.Form):
    """Typed-name e-signature (mock)."""
    signed_name = forms.CharField(
        max_length=160, label='Type your full name to sign',
        widget=forms.TextInput(attrs={'placeholder': 'Your full legal name'}),
    )
    agree = forms.BooleanField(
        label='I have read and agree to this contract, and intend this typed '
              'name to be my signature.',
    )

    def clean_signed_name(self):
        name = (self.cleaned_data.get('signed_name') or '').strip()
        if not name:
            raise forms.ValidationError('Type your full name to sign.')
        return name


class DeclineForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Reason for declining'}),
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason


# ---------- Amendment ----------

class AmendmentForm(forms.ModelForm):
    class Meta:
        model = ContractAmendment
        fields = [
            'title', 'change_type', 'description', 'new_value', 'new_end_date',
            'new_body', 'effective_date',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'new_body': forms.Textarea(attrs={'rows': 4}),
            'new_value': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'new_end_date': forms.DateInput(attrs={'type': 'date'}),
            'effective_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get('new_value') is None
                and not cleaned.get('new_end_date')
                and not (cleaned.get('new_body') or '').strip()):
            raise forms.ValidationError(
                'An amendment must change at least one of: value, end date or body.')
        return cleaned


# ---------- Obligation ----------

class ObligationForm(forms.ModelForm):
    class Meta:
        model = ContractObligation
        fields = [
            'obligation_type', 'title', 'description', 'due_date', 'amount',
            'penalty_amount', 'account_code', 'responsible_party', 'owner',
            'status', 'notes',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'amount': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'penalty_amount': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account_code'].required = False
        self.fields['owner'].required = False
        if tenant is not None:
            from apps.requisitions.models import AccountCode
            self.fields['account_code'].queryset = AccountCode.objects.filter(
                tenant=tenant, is_active=True,
            )
            self.fields['owner'].queryset = self.fields['owner'].queryset.filter(
                tenant=tenant, is_active=True,
            )


# ---------- Documents ----------

class ContractDocumentForm(forms.ModelForm):
    ALLOWED_EXTENSIONS = (
        'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt',
        'png', 'jpg', 'jpeg', 'zip',
    )

    class Meta:
        model = ContractDocument
        fields = ['title', 'file', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}

    def clean_file(self):
        f = self.cleaned_data.get('file')
        if f:
            if f.size > 10 * 1024 * 1024:
                raise forms.ValidationError('File size must be 10 MB or less.')
            name = getattr(f, 'name', '') or ''
            ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
            if ext not in self.ALLOWED_EXTENSIONS:
                raise forms.ValidationError(
                    'Unsupported file type. Allowed: '
                    + ', '.join(self.ALLOWED_EXTENSIONS) + '.'
                )
        return f


# ---------- Lifecycle action forms ----------

class TerminateContractForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 2,
                                     'placeholder': 'Why are you terminating this contract?'}),
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason


class CancelContractForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 2,
                                     'placeholder': 'Why are you cancelling this contract?'}),
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason


class SaveAsTemplateForm(forms.Form):
    title = forms.CharField(max_length=200, label='Template title')
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'rows': 2}),
    )
    is_shared = forms.BooleanField(
        required=False, initial=True, label='Share with the whole tenant',
    )


class ApplyTemplateForm(forms.Form):
    template = forms.ModelChoiceField(queryset=ContractTemplate.objects.none())

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant is not None:
            self.fields['template'].queryset = ContractTemplate.objects.filter(
                tenant=tenant, archived=False,
            )

"""Module 5 forms: vendor CRUD + classification/segment/risk/onboarding/blacklist."""
from django import forms

from .models import (
    Vendor, VendorBankAccount, VendorBlacklistEvent, VendorCategory,
    VendorContact, VendorDocument, VendorOnboardingApplication,
    VendorRiskAssessment, VendorSegment,
)


# ---------- Classification & Segmentation ----------

class VendorCategoryForm(forms.ModelForm):
    class Meta:
        model = VendorCategory
        fields = ['name', 'code', 'parent', 'description', 'is_active']

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant is not None:
            qs = VendorCategory.objects.filter(tenant=tenant, is_active=True)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            self.fields['parent'].queryset = qs

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip()
        if not code:
            raise forms.ValidationError('Code is required.')
        if self.tenant:
            qs = VendorCategory.all_objects.filter(tenant=self.tenant, code__iexact=code)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    'A category with this code already exists for this tenant.'
                )
        return code


class VendorSegmentForm(forms.ModelForm):
    COLOR_CHOICES = [
        ('primary', 'Blue'),
        ('success', 'Green'),
        ('warning', 'Orange'),
        ('danger', 'Red'),
        ('info', 'Cyan'),
        ('secondary', 'Grey'),
    ]
    color = forms.ChoiceField(choices=COLOR_CHOICES)

    class Meta:
        model = VendorSegment
        fields = ['name', 'code', 'color', 'description', 'is_active']

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip()
        if not code:
            raise forms.ValidationError('Code is required.')
        if self.tenant:
            qs = VendorSegment.all_objects.filter(tenant=self.tenant, code__iexact=code)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    'A segment with this code already exists for this tenant.'
                )
        return code


# ---------- Vendor + sub-records ----------

class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = [
            'legal_name', 'trade_name', 'vendor_type', 'tax_id',
            'registration_number', 'email', 'phone', 'website',
            'country', 'address_line1', 'address_line2',
            'city', 'state', 'postal_code',
            'primary_contact_name', 'primary_contact_email', 'primary_contact_phone',
            'category', 'segment', 'notes',
        ]
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant is not None:
            self.fields['category'].queryset = VendorCategory.objects.filter(
                tenant=tenant, is_active=True,
            )
            self.fields['segment'].queryset = VendorSegment.objects.filter(
                tenant=tenant, is_active=True,
            )


class VendorContactForm(forms.ModelForm):
    class Meta:
        model = VendorContact
        fields = ['name', 'role', 'email', 'phone', 'is_primary', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}


class VendorDocumentForm(forms.ModelForm):
    class Meta:
        model = VendorDocument
        fields = ['doc_type', 'title', 'file', 'description', 'expires_at']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'expires_at': forms.DateInput(attrs={'type': 'date'}),
        }


class VendorBankAccountForm(forms.ModelForm):
    class Meta:
        model = VendorBankAccount
        fields = [
            'bank_name', 'account_holder', 'account_number', 'branch',
            'iban', 'swift_code', 'currency', 'country', 'is_primary', 'notes',
        ]
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}


# ---------- Onboarding ----------

class VendorOnboardingApplicationForm(forms.ModelForm):
    """Public-facing supplier application form. Anonymous users."""

    class Meta:
        model = VendorOnboardingApplication
        fields = [
            'company_name', 'trade_name', 'vendor_type',
            'contact_name', 'contact_email', 'contact_phone',
            'country', 'tax_id', 'registration_number', 'website',
            'service_description',
        ]
        widgets = {
            'service_description': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Describe the goods or services you offer...',
            }),
        }


class OnboardingReviewForm(forms.Form):
    """Admin form: approve (-> convert to vendor) or reject."""

    ACTION_CHOICES = [
        ('approve', 'Approve & convert to vendor'),
        ('reject', 'Reject'),
        ('under_review', 'Mark under review'),
    ]
    action = forms.ChoiceField(choices=ACTION_CHOICES)
    notes = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'rows': 2}),
        help_text='Optional review notes.',
    )
    rejection_reason = forms.CharField(
        required=False, max_length=255,
        help_text='Required when rejecting.',
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('action') == 'reject' and not (cleaned.get('rejection_reason') or '').strip():
            raise forms.ValidationError('Rejection reason is required.')
        return cleaned


# ---------- Risk Profiling ----------

class VendorRiskAssessmentForm(forms.ModelForm):
    class Meta:
        model = VendorRiskAssessment
        fields = [
            'assessment_date', 'valid_until',
            'financial_score', 'operational_score',
            'compliance_score', 'quality_score', 'notes',
        ]
        widgets = {
            'assessment_date': forms.DateInput(attrs={'type': 'date'}),
            'valid_until': forms.DateInput(attrs={'type': 'date'}),
            'financial_score': forms.NumberInput(attrs={'min': 0, 'max': 100, 'step': 1}),
            'operational_score': forms.NumberInput(attrs={'min': 0, 'max': 100, 'step': 1}),
            'compliance_score': forms.NumberInput(attrs={'min': 0, 'max': 100, 'step': 1}),
            'quality_score': forms.NumberInput(attrs={'min': 0, 'max': 100, 'step': 1}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }


# ---------- Blacklist ----------

class VendorBlacklistEventForm(forms.ModelForm):
    """Suspend / blacklist / reinstate dialog."""

    class Meta:
        model = VendorBlacklistEvent
        fields = ['action', 'effective_date', 'end_date', 'reason', 'notes']
        widgets = {
            'effective_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.TextInput(attrs={'maxlength': 255}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get('action')
        if action == 'suspend' and not cleaned.get('end_date'):
            # end_date optional even for suspensions, but warn through help_text
            pass
        if action == 'blacklist' and cleaned.get('end_date'):
            raise forms.ValidationError(
                'Blacklisting is permanent — leave the end date blank.'
            )
        if not (cleaned.get('reason') or '').strip():
            raise forms.ValidationError('A reason is required.')
        return cleaned


# ---------- Portal invite ----------

class VendorPortalInviteForm(forms.Form):
    email = forms.EmailField(
        required=False,
        help_text='Leave blank to use the vendor primary contact email.',
    )


# ---------- Vendor portal: self-service ----------

class VendorPortalProfileForm(forms.ModelForm):
    """Vendor-side editable subset of the Vendor record."""

    class Meta:
        model = Vendor
        fields = [
            'trade_name', 'email', 'phone', 'website',
            'country', 'address_line1', 'address_line2',
            'city', 'state', 'postal_code',
            'primary_contact_name', 'primary_contact_email', 'primary_contact_phone',
        ]

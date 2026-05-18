"""Forms for Module 1 (plans, subscriptions, branding, security, onboarding)."""
from django import forms

from apps.core.models import Tenant
from .models import (
    BrandingSettings, Plan, SecuritySettings, Subscription,
)


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = (
            'name', 'slug', 'description',
            'price_monthly', 'price_yearly', 'currency', 'trial_days',
            'max_users', 'max_storage_gb', 'max_vendors',
            'max_purchase_orders_per_month',
            'features', 'is_active', 'is_public', 'sort_order',
        )
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'features': forms.Textarea(attrs={
                'rows': 4, 'placeholder': '["Feature 1", "Feature 2"]',
            }),
        }


class SubscriptionAssignForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ('plan', 'billing_cycle', 'auto_renew')


class BrandingForm(forms.ModelForm):
    class Meta:
        model = BrandingSettings
        fields = (
            'logo', 'logo_dark', 'favicon',
            'primary_color', 'secondary_color', 'login_background',
            'email_from_name', 'email_from_address', 'email_signature',
            'support_url', 'support_email',
        )
        widgets = {
            'primary_color': forms.TextInput(attrs={'type': 'color'}),
            'secondary_color': forms.TextInput(attrs={'type': 'color'}),
            'email_signature': forms.Textarea(attrs={'rows': 4}),
        }


class SecurityForm(forms.ModelForm):
    class Meta:
        model = SecuritySettings
        fields = (
            'password_min_length', 'password_require_uppercase',
            'password_require_number', 'password_require_special',
            'password_expiry_days', 'mfa_required',
            'session_timeout_minutes', 'ip_allowlist', 'allowed_login_domains',
        )
        widgets = {
            'ip_allowlist': forms.Textarea(attrs={
                'rows': 3, 'placeholder': '10.0.0.0/24\n192.168.1.0/24',
            }),
        }


class OnboardingCompanyForm(forms.ModelForm):
    """Step 2 of the onboarding wizard — company details."""

    class Meta:
        model = Tenant
        fields = (
            'name', 'slug', 'domain', 'email', 'phone',
            'address', 'website', 'industry', 'timezone',
        )
        widgets = {'address': forms.Textarea(attrs={'rows': 2})}


class OnboardingPlanForm(forms.Form):
    """Step 3 of the onboarding wizard — pick a plan."""

    plan = forms.ModelChoiceField(
        queryset=Plan.objects.filter(is_active=True, is_public=True),
        widget=forms.RadioSelect, empty_label=None,
    )
    billing_cycle = forms.ChoiceField(
        choices=Subscription.BILLING_CYCLES,
        widget=forms.RadioSelect, initial='monthly',
    )

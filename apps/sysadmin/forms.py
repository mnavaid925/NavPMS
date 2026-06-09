"""Module 21 forms. Clone the dms ``__init__(self, *args, tenant=None, **kwargs)`` idiom; scope FK
querysets to the tenant; set optional fields ``required=False``.

SECURITY: SSO secrets (``client_secret`` / ``bind_password``) use ``PasswordInput(render_value=False)``
so a stored secret is never echoed back into the HTML, and a blank submit preserves the existing
value (it is not wiped). The API-key secret is never a form field at all — it is generated server-side
and shown once.
"""
from django import forms

from .connectors import validate_metadata_url
from .models import (
    BackupPolicy, Currency, IdentityProvider, NumberSequence, RestoreRequest, RoleDefinition,
    SystemConfiguration, TaxCode, Webhook,
)
from .permissions import PERMISSION_CATALOG
from .webhooks import WEBHOOK_EVENTS, validate_webhook_url

_PERMISSION_CHOICES = [
    (code, label) for _group, prs in PERMISSION_CATALOG for code, label in prs
]


class BootstrapFormMixin:
    """Apply Bootstrap 5 control classes to every widget (the project styles ``.form-control`` /
    ``.form-select``, not bare inputs)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                continue
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')


class RoleDefinitionForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = RoleDefinition
        fields = ['code', 'name', 'description', 'is_active']
        widgets = {'description': forms.TextInput()}

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['description'].required = False
        # A built-in role's code is immutable (it maps to User.role).
        if self.instance and self.instance.pk and self.instance.is_system:
            self.fields['code'].disabled = True
            self.fields['code'].help_text = 'Built-in role code — cannot be changed.'


class IdentityProviderForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = IdentityProvider
        fields = [
            'name', 'protocol', 'is_active', 'is_default',
            'entity_id', 'sso_url', 'slo_url', 'metadata_url', 'x509_cert',
            'client_id', 'client_secret',
            'server_uri', 'bind_dn', 'bind_password', 'user_search_base', 'user_filter',
            'jit_provisioning', 'default_role_code', 'allowed_domains',
        ]
        widgets = {
            'client_secret': forms.PasswordInput(render_value=False),
            'bind_password': forms.PasswordInput(render_value=False),
            'x509_cert': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        # Remember stored secrets so a blank submit keeps (not wipes) them.
        self._orig_client_secret = self.instance.client_secret if self.instance.pk else ''
        self._orig_bind_password = self.instance.bind_password if self.instance.pk else ''
        for name in ('entity_id', 'sso_url', 'slo_url', 'metadata_url', 'x509_cert', 'client_id',
                     'client_secret', 'server_uri', 'bind_dn', 'bind_password', 'user_search_base',
                     'allowed_domains'):
            self.fields[name].required = False
        if self.instance.pk and self.instance.has_secret:
            for name in ('client_secret', 'bind_password'):
                self.fields[name].help_text = 'Leave blank to keep the current value.'

    def clean_metadata_url(self):
        url = self.cleaned_data.get('metadata_url', '')
        if url:
            validate_metadata_url(url)  # raises ValidationError on an unsafe target
        return url

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not self.cleaned_data.get('client_secret'):
            obj.client_secret = self._orig_client_secret
        if not self.cleaned_data.get('bind_password'):
            obj.bind_password = self._orig_bind_password
        if commit:
            obj.save()
        return obj


class SystemConfigurationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = SystemConfiguration
        fields = [
            'company_legal_name', 'base_currency_code', 'fiscal_year_start_month',
            'date_format', 'time_format', 'decimal_places', 'prices_include_tax',
            'default_payment_terms_days', 'default_tax_code', 'weekend_days', 'locale',
        ]

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['company_legal_name'].required = False
        self.fields['default_tax_code'].required = False
        if tenant is not None:
            self.fields['default_tax_code'].queryset = TaxCode.objects.filter(
                tenant=tenant, is_active=True).order_by('code')


class CurrencyForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Currency
        fields = ['code', 'name', 'symbol', 'decimal_places', 'exchange_rate_to_base',
                  'is_base', 'is_active']

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['symbol'].required = False

    def clean_code(self):
        return (self.cleaned_data.get('code') or '').upper()[:3]


class TaxCodeForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = TaxCode
        fields = ['code', 'name', 'rate', 'tax_type', 'jurisdiction', 'is_default', 'is_active']

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['jurisdiction'].required = False


class NumberSequenceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = NumberSequence
        fields = ['doc_type', 'name', 'prefix', 'suffix', 'padding', 'next_number',
                  'include_year', 'reset_frequency', 'is_active']

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        for name in ('prefix', 'suffix'):
            self.fields[name].required = False


class BackupPolicyForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BackupPolicy
        fields = ['name', 'frequency', 'scope', 'retention_days', 'storage_target',
                  'storage_location', 'encryption_enabled', 'run_hour', 'is_active']

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['storage_location'].required = False


class RestoreRequestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = RestoreRequest
        fields = ['reason']
        widgets = {'reason': forms.Textarea(attrs={'rows': 3,
                   'placeholder': 'Why is a restore needed? (audit trail)'})}

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['reason'].required = False


class WebhookForm(BootstrapFormMixin, forms.ModelForm):
    events = forms.MultipleChoiceField(
        choices=WEBHOOK_EVENTS, required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Events that trigger a POST to the target URL.')

    class Meta:
        model = Webhook
        fields = ['name', 'target_url', 'events', 'secret', 'is_active']
        widgets = {'secret': forms.PasswordInput(render_value=False)}

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self._orig_secret = self.instance.secret if self.instance.pk else ''
        self.fields['secret'].required = False
        if self.instance.pk:
            self.fields['events'].initial = self.instance.events or []
            if self.instance.secret:
                self.fields['secret'].help_text = 'Leave blank to keep the current signing secret.'

    def clean_target_url(self):
        url = self.cleaned_data.get('target_url', '')
        if url:
            validate_webhook_url(url)  # raises ValidationError on an unsafe target (SSRF guard)
        return url

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.events = self.cleaned_data.get('events', [])
        if not self.cleaned_data.get('secret'):
            obj.secret = self._orig_secret
        if commit:
            obj.save()
        return obj


class ApiKeyIssueForm(BootstrapFormMixin, forms.Form):
    """Issuing an API key — the secret is generated server-side, never entered here."""

    name = forms.CharField(max_length=120)
    scopes = forms.MultipleChoiceField(
        choices=_PERMISSION_CHOICES, required=False, widget=forms.CheckboxSelectMultiple,
        help_text='Permission scopes this key may exercise.')
    expires_at = forms.DateTimeField(
        required=False, widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='Optional expiry date.')

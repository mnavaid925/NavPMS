"""Module 20 forms: documents, version uploads, best-practice templates.

A ``tenant=`` kwarg scopes every FK dropdown (owner) to the current tenant, mirroring the
compliance / budget style. No crispy — templates render fields individually.
"""
from django import forms

from apps.accounts.models import User

from .models import Document, DocumentVersion, PolicyTemplate


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['title', 'category', 'confidentiality', 'tags', 'owner', 'summary']
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 2}),
            'tags': forms.TextInput(attrs={'placeholder': 'e.g. laptops, warranty, 2026'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['summary'].required = False
        self.fields['tags'].required = False
        self.fields['owner'].required = False
        if tenant is not None:
            self.fields['owner'].queryset = User.objects.filter(
                tenant=tenant, is_active=True).order_by('username')
        self.fields['owner'].label = 'Document owner'


class DocumentVersionForm(forms.ModelForm):
    publish = forms.BooleanField(
        required=False, label='Publish this version now',
        help_text='Make it the current downloadable version (supersedes the previous one).')

    class Meta:
        model = DocumentVersion
        fields = ['file', 'change_note']
        widgets = {
            'change_note': forms.TextInput(attrs={'placeholder': 'What changed in this version?'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['change_note'].required = False
        self.fields['file'].label = 'File (PDF / DOCX / TXT / MD / CSV / XLSX, max 10 MB)'


class PolicyTemplateForm(forms.ModelForm):
    class Meta:
        model = PolicyTemplate
        fields = ['title', 'category', 'description', 'body', 'owner']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'body': forms.Textarea(attrs={'rows': 12}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['description'].required = False
        self.fields['owner'].required = False
        if tenant is not None:
            self.fields['owner'].queryset = User.objects.filter(
                tenant=tenant, is_active=True).order_by('username')
        self.fields['owner'].label = 'Template owner'

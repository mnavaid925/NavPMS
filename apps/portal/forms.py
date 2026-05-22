"""Forms for Module 2 (widgets, notifications, quick requisitions, reports)."""
from django import forms

from .models import (
    DashboardWidget, Notification, QuickRequisition, QuickRequisitionItem,
    SavedReport,
)


class DashboardWidgetForm(forms.ModelForm):
    class Meta:
        model = DashboardWidget
        fields = ('widget_type', 'title', 'size', 'position', 'is_visible')
        widgets = {
            'position': forms.NumberInput(attrs={'min': 0}),
        }


class NotificationForm(forms.ModelForm):
    class Meta:
        model = Notification
        fields = ('category', 'priority', 'title', 'message', 'link_url')
        widgets = {
            'message': forms.Textarea(attrs={'rows': 3}),
            'link_url': forms.TextInput(attrs={'placeholder': '/portal/requisitions/'}),
        }

    def clean_link_url(self):
        """Reject script-scheme URIs (javascript:, data:, vbscript:, …).

        link_url is rendered as an <a href> in the notification detail page;
        auto-escaping does not neutralise script-scheme URIs, so a value such
        as ``javascript:alert(1)`` would execute on click (SQA defect D-02).
        Only http(s) and site-relative paths are allowed.
        """
        url = (self.cleaned_data.get('link_url') or '').strip()
        if not url:
            return url
        if url.startswith(('/', '#', '?')):
            return url
        if url.lower().startswith(('http://', 'https://')):
            return url
        raise forms.ValidationError(
            'Enter a relative path (starting with /) or an http(s):// URL.'
        )


class QuickRequisitionForm(forms.ModelForm):
    class Meta:
        model = QuickRequisition
        fields = (
            'title', 'category', 'priority', 'vendor_name', 'needed_by',
            'description', 'justification', 'currency',
        )
        widgets = {
            'needed_by': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'justification': forms.Textarea(attrs={'rows': 3}),
        }


class QuickRequisitionItemForm(forms.ModelForm):
    """Rendered field-by-field (not crispy) inside the requisition detail page,
    so each widget carries its own Bootstrap class."""

    class Meta:
        model = QuickRequisitionItem
        fields = ('name', 'quantity', 'unit', 'unit_price')
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'e.g. A4 paper ream',
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'step': '0.01',
            }),
            'unit': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'unit',
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'step': '0.01',
            }),
        }


class SavedReportForm(forms.ModelForm):
    class Meta:
        model = SavedReport
        fields = ('name', 'report_type', 'date_from', 'date_to')
        widgets = {
            'date_from': forms.DateInput(attrs={'type': 'date'}),
            'date_to': forms.DateInput(attrs={'type': 'date'}),
        }

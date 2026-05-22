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

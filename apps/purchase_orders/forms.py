"""Module 11 forms: purchase-order header, line items, change orders, documents
and the lifecycle actions (issue / acknowledge / decline / cancel / close / receive).

Mirrors the contracts form style: a ``tenant=`` kwarg scopes FK dropdowns
(category / vendor / account_code / requisition) to the current tenant, ``date``
widgets drive the date fields, and lightweight ``forms.Form`` classes back the
lifecycle actions.
"""
from django import forms

from apps.vendors.models import Vendor

from .models import (
    DISPATCH_METHOD_CHOICES,
    PurchaseOrder,
    PurchaseOrderChangeOrder,
    PurchaseOrderDocument,
    PurchaseOrderLine,
)


# ---------- Purchase order header ----------

class PurchaseOrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = [
            'title', 'description', 'category', 'vendor', 'requisition',
            'currency', 'tax_amount', 'shipping_amount', 'order_date',
            'expected_delivery_date', 'payment_terms', 'shipping_address',
            'owner', 'notes',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'shipping_address': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
            'order_date': forms.DateInput(attrs={'type': 'date'}),
            'expected_delivery_date': forms.DateInput(attrs={'type': 'date'}),
            'tax_amount': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'shipping_amount': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        # Vendor is optional at draft (a PO generated from a requisition has none);
        # it is required before the PO can be issued (enforced in the service).
        self.fields['vendor'].required = False
        self.fields['category'].required = False
        self.fields['owner'].required = False
        self.fields['requisition'].required = False
        if tenant is not None:
            from apps.requisitions.models import Requisition
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
            self.fields['requisition'].queryset = Requisition.objects.filter(
                tenant=tenant,
            )

    def clean(self):
        cleaned = super().clean()
        order_date = cleaned.get('order_date')
        delivery = cleaned.get('expected_delivery_date')
        if order_date and delivery and delivery < order_date:
            self.add_error(
                'expected_delivery_date',
                'Expected delivery date cannot be before the order date.',
            )
        return cleaned


# ---------- Line item ----------

class PurchaseOrderLineForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrderLine
        fields = [
            'line_no', 'description', 'sku', 'uom', 'quantity', 'unit_price',
            'account_code', 'required_date', 'notes',
        ]
        widgets = {
            'line_no': forms.NumberInput(attrs={'min': 1, 'step': 1}),
            'quantity': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'unit_price': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'required_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.TextInput(),
        }

    def __init__(self, *args, tenant=None, purchase_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.purchase_order = purchase_order
        self.fields['account_code'].required = False
        self.fields['sku'].required = False
        self.fields['notes'].required = False
        if tenant is not None:
            from apps.requisitions.models import AccountCode
            self.fields['account_code'].queryset = AccountCode.objects.filter(
                tenant=tenant, is_active=True,
            )

    def clean_line_no(self):
        line_no = self.cleaned_data.get('line_no') or 1
        if self.purchase_order:
            qs = PurchaseOrderLine.all_objects.filter(
                purchase_order=self.purchase_order, line_no=line_no,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f'Line number {line_no} already exists on this PO.')
        return line_no


# ---------- Change order ----------

class ChangeOrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrderChangeOrder
        fields = ['change_type', 'reason', 'new_expected_delivery_date', 'effective_date']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 3}),
            'new_expected_delivery_date': forms.DateInput(attrs={'type': 'date'}),
            'effective_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Give a reason for this change order.')
        return reason


# ---------- Documents ----------

class PurchaseOrderDocumentForm(forms.ModelForm):
    ALLOWED_EXTENSIONS = (
        'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt',
        'png', 'jpg', 'jpeg', 'zip',
    )

    class Meta:
        model = PurchaseOrderDocument
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

class IssuePOForm(forms.Form):
    """Dispatch dialog: how the PO is sent and to which email (snapshot)."""
    dispatch_method = forms.ChoiceField(
        choices=DISPATCH_METHOD_CHOICES, initial='portal',
    )
    recipient_email = forms.EmailField(
        required=False, label='Recipient email (optional)',
        help_text="Defaults to the supplier's email on file.",
    )


class AcknowledgePOForm(forms.Form):
    note = forms.CharField(
        required=False, max_length=255,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional note'}),
    )


class DeclinePOForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Reason for declining'}),
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason


class CancelPOForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 2,
                                     'placeholder': 'Why are you cancelling this PO?'}),
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason


class CloseoutForm(forms.Form):
    note = forms.CharField(
        required=False, max_length=255,
        widget=forms.Textarea(attrs={'rows': 2,
                                     'placeholder': 'Optional close-out note'}),
    )


class ReceiveLineForm(forms.Form):
    received_quantity = forms.DecimalField(
        min_value=0, max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
    )

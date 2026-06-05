"""Module 14 forms: supplier-invoice header + lines, OCR capture, payment terms,
payment vouchers, and the lifecycle action forms (dispute / reject / cancel).

Mirrors the goods_receipt / purchase_orders form style: a ``tenant=`` kwarg scopes FK
dropdowns to the current tenant, ``date`` widgets drive date fields, file uploads run through
the shared whitelist (:func:`apps.invoicing.services.upload_error`), and lightweight
``forms.Form`` classes back the lifecycle actions.
"""
from django import forms

from apps.purchase_orders.models import PO_DISPATCHED_STATUSES, PurchaseOrder
from apps.vendors.models import Vendor
from apps.requisitions.models import AccountCode
from apps.goods_receipt.models import GoodsReceiptLine

from . import services
from .models import (
    PAYMENT_METHOD_CHOICES,
    PaymentTerm,
    PaymentVoucher,
    SupplierInvoice,
    SupplierInvoiceLine,
)


def _active_vendor_qs(tenant):
    return (
        Vendor.objects.filter(tenant=tenant)
        .exclude(status__in=('blacklisted', 'inactive'))
        .order_by('legal_name')
    )


def _invoiceable_po_qs(tenant):
    return (
        PurchaseOrder.objects.filter(tenant=tenant, status__in=PO_DISPATCHED_STATUSES)
        .exclude(vendor__isnull=True)
        .order_by('-issued_at', '-created_at')
    )


# ---------- Invoice capture (OCR upload) ----------

class InvoiceCaptureForm(forms.Form):
    """Upload a supplier invoice PDF/image for OCR capture (optionally against a PO)."""

    purchase_order = forms.ModelChoiceField(
        queryset=PurchaseOrder.objects.none(), required=False,
        help_text='Match against this purchase order (recommended).')
    vendor = forms.ModelChoiceField(
        queryset=Vendor.objects.none(), required=False,
        help_text='Required only for a non-PO invoice.')
    source_file = forms.FileField(
        required=True, help_text='PDF or image (PDF / JPG / PNG / TIFF / TXT, 10 MB max).')
    supplier_invoice_ref = forms.CharField(max_length=80, required=False)

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant is not None:
            self.fields['purchase_order'].queryset = _invoiceable_po_qs(tenant)
            self.fields['vendor'].queryset = _active_vendor_qs(tenant)

    def clean_source_file(self):
        f = self.cleaned_data.get('source_file')
        err = services.upload_error(f)
        if err:
            raise forms.ValidationError(err)
        return f

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('purchase_order') and not cleaned.get('vendor'):
            raise forms.ValidationError(
                'Select a purchase order or a supplier for this invoice.')
        return cleaned


# ---------- Invoice header (manual create / edit) ----------

class SupplierInvoiceForm(forms.ModelForm):
    class Meta:
        model = SupplierInvoice
        fields = [
            'vendor', 'purchase_order', 'payment_term', 'supplier_invoice_ref',
            'invoice_date', 'received_date', 'currency', 'tax_amount', 'shipping_amount',
            'notes',
        ]
        widgets = {
            'invoice_date': forms.DateInput(attrs={'type': 'date'}),
            'received_date': forms.DateInput(attrs={'type': 'date'}),
            'tax_amount': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'shipping_amount': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        for f in ('purchase_order', 'payment_term', 'supplier_invoice_ref',
                  'received_date', 'tax_amount', 'shipping_amount', 'notes'):
            self.fields[f].required = False
        if tenant is not None:
            self.fields['vendor'].queryset = _active_vendor_qs(tenant)
            self.fields['purchase_order'].queryset = _invoiceable_po_qs(tenant)
            self.fields['payment_term'].queryset = PaymentTerm.objects.filter(
                tenant=tenant, is_active=True).order_by('code')
        # Vendor + PO are fixed once the invoice (and its matched lines) exist.
        if self.instance and self.instance.pk:
            self.fields['vendor'].disabled = True
            self.fields['purchase_order'].disabled = True

    def clean(self):
        cleaned = super().clean()
        po = cleaned.get('purchase_order')
        vendor = cleaned.get('vendor')
        if po is not None and vendor is not None and po.vendor_id != vendor.id:
            self.add_error(
                'vendor', 'The supplier must match the purchase order’s supplier.')
        return cleaned


# ---------- Invoice line ----------

class SupplierInvoiceLineForm(forms.ModelForm):
    class Meta:
        model = SupplierInvoiceLine
        fields = [
            'purchase_order_line', 'goods_receipt_line', 'account_code', 'description',
            'uom', 'quantity', 'unit_price', 'tax_amount', 'notes',
        ]
        widgets = {
            'quantity': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'unit_price': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'tax_amount': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'notes': forms.TextInput(),
        }

    def __init__(self, *args, tenant=None, supplier_invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.supplier_invoice = supplier_invoice
        for f in ('purchase_order_line', 'goods_receipt_line', 'account_code', 'uom',
                  'tax_amount', 'notes', 'description'):
            self.fields[f].required = False
        self.fields['purchase_order_line'].label = 'PO line'
        self.fields['goods_receipt_line'].label = 'GRN line'
        po = supplier_invoice.purchase_order if supplier_invoice else None
        if po is not None:
            self.fields['purchase_order_line'].queryset = (
                po.lines.exclude(delivery_status='cancelled').order_by('line_no'))
            self.fields['goods_receipt_line'].queryset = (
                GoodsReceiptLine.objects.filter(
                    purchase_order_line__purchase_order=po)
                .exclude(goods_receipt__status='cancelled')
                .order_by('line_no'))
        else:
            self.fields['purchase_order_line'].queryset = (
                SupplierInvoiceLine._meta.get_field('purchase_order_line')
                .related_model.objects.none())
            self.fields['goods_receipt_line'].queryset = GoodsReceiptLine.objects.none()
        if tenant is not None:
            self.fields['account_code'].queryset = AccountCode.objects.filter(
                tenant=tenant, is_active=True).order_by('code')

    def clean_quantity(self):
        qty = self.cleaned_data.get('quantity')
        if qty is None or qty <= 0:
            raise forms.ValidationError('Quantity must be greater than zero.')
        return qty


# ---------- Payment term master ----------

class PaymentTermForm(forms.ModelForm):
    class Meta:
        model = PaymentTerm
        fields = [
            'code', 'name', 'net_days', 'discount_percent', 'discount_days',
            'is_active', 'description',
        ]
        widgets = {
            'discount_percent': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'description': forms.TextInput(),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['description'].required = False

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip()
        if not code:
            raise forms.ValidationError('A code is required.')
        qs = PaymentTerm.objects.filter(tenant=self.tenant, code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('A payment term with this code already exists.')
        return code


# ---------- Payment voucher ----------

class CreateVoucherForm(forms.Form):
    take_discount = forms.BooleanField(
        required=False, help_text='Take the early-payment discount if still available.')
    payment_method = forms.ChoiceField(
        choices=PAYMENT_METHOD_CHOICES, initial='bank_transfer')
    scheduled_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={'type': 'date'}))


class PayVoucherForm(forms.Form):
    payment_method = forms.ChoiceField(
        choices=PAYMENT_METHOD_CHOICES, initial='bank_transfer')
    reference = forms.CharField(max_length=120, required=False)


# ---------- Lifecycle action forms ----------

class DisputeForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Describe the discrepancy…'}))

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please describe the issue.')
        return reason


class DisputeNoteForm(forms.Form):
    body = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Add a message…'}))

    def clean_body(self):
        body = (self.cleaned_data.get('body') or '').strip()
        if not body:
            raise forms.ValidationError('A message is required.')
        return body


class ReasonForm(forms.Form):
    """Generic reason capture for reject / cancel."""

    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Reason…'}))

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason

"""Module 13 forms: GRN header, GRN lines, the QA inspection checklist, and the
Return-to-Vendor header/line + lifecycle actions.

Mirrors the purchase_orders / fulfillment form style: a ``tenant=`` kwarg scopes FK
dropdowns to the current tenant, ``date`` widgets drive date fields, and lightweight
``forms.Form`` classes back the lifecycle actions. The per-line accept/reject inputs are
read directly from ``request.POST`` in the view (``accepted_<id>`` etc.), mirroring the
``recv_<id>`` pattern in fulfillment's delivery confirmation.
"""
from django import forms

from apps.fulfillment.models import ShipmentLine
from apps.purchase_orders.models import (
    PO_CHANGE_ORDERABLE_STATUSES,
    PurchaseOrder,
)

from .models import (
    GoodsReceipt,
    GoodsReceiptLine,
    ReturnToVendor,
    ReturnToVendorLine,
)


# ---------- GRN header ----------

class GoodsReceiptForm(forms.ModelForm):
    class Meta:
        model = GoodsReceipt
        fields = [
            'purchase_order', 'shipment', 'received_date', 'delivery_note_ref',
            'warehouse_location', 'carrier_note', 'notes',
        ]
        widgets = {
            'received_date': forms.DateInput(attrs={'type': 'date'}),
            'carrier_note': forms.TextInput(),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        for f in ('shipment', 'delivery_note_ref', 'warehouse_location',
                  'carrier_note', 'notes', 'received_date'):
            self.fields[f].required = False
        self.fields['shipment'].help_text = 'Optional — the ASN these goods arrived on.'
        # The parent PO is fixed once the GRN exists.
        if self.instance and self.instance.pk:
            self.fields['purchase_order'].disabled = True
        if tenant is not None:
            self.fields['purchase_order'].queryset = (
                PurchaseOrder.objects.filter(
                    tenant=tenant, status__in=PO_CHANGE_ORDERABLE_STATUSES,
                ).exclude(vendor__isnull=True).order_by('-issued_at', '-created_at')
            )
        # Scope the optional shipment to the chosen PO once it is known.
        po = None
        if self.instance and self.instance.pk:
            po = self.instance.purchase_order
        elif self.initial.get('purchase_order'):
            po = self.initial['purchase_order']
        if po is not None:
            self.fields['shipment'].queryset = po.shipments.exclude(status='cancelled')
        elif tenant is not None:
            from apps.fulfillment.models import Shipment
            self.fields['shipment'].queryset = Shipment.objects.filter(tenant=tenant)


# ---------- GRN line ----------

class GoodsReceiptLineForm(forms.ModelForm):
    class Meta:
        model = GoodsReceiptLine
        fields = [
            'purchase_order_line', 'shipment_line', 'received_quantity',
            'discrepancy_type', 'notes',
        ]
        widgets = {
            'received_quantity': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'notes': forms.TextInput(),
        }

    def __init__(self, *args, tenant=None, goods_receipt=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.goods_receipt = goods_receipt
        self.fields['shipment_line'].required = False
        self.fields['notes'].required = False
        self.fields['purchase_order_line'].label = 'PO line'
        if goods_receipt is not None:
            self.fields['purchase_order_line'].queryset = (
                goods_receipt.purchase_order.lines.exclude(delivery_status='cancelled')
            )
            if goods_receipt.shipment_id:
                self.fields['shipment_line'].queryset = (
                    goods_receipt.shipment.lines.all()
                )
            else:
                self.fields['shipment_line'].queryset = ShipmentLine.objects.none()

    def clean_received_quantity(self):
        qty = self.cleaned_data.get('received_quantity')
        if qty is None or qty <= 0:
            raise forms.ValidationError('Received quantity must be greater than zero.')
        return qty


# ---------- Return to Vendor ----------

class ReturnToVendorForm(forms.ModelForm):
    class Meta:
        model = ReturnToVendor
        fields = ['reason', 'rma_number']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reason'].required = False
        self.fields['rma_number'].required = False


class RTVLineForm(forms.ModelForm):
    class Meta:
        model = ReturnToVendorLine
        fields = ['goods_receipt_line', 'quantity', 'reason']
        widgets = {
            'quantity': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'reason': forms.TextInput(),
        }

    def __init__(self, *args, goods_receipt=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.goods_receipt = goods_receipt
        self.fields['reason'].required = False
        self.fields['goods_receipt_line'].label = 'GRN line'
        if goods_receipt is not None:
            self.fields['goods_receipt_line'].queryset = (
                goods_receipt.lines.filter(rejected_quantity__gt=0)
            )

    def clean(self):
        cleaned = super().clean()
        line = cleaned.get('goods_receipt_line')
        qty = cleaned.get('quantity')
        if line and qty is not None:
            if qty <= 0:
                self.add_error('quantity', 'Quantity must be greater than zero.')
            elif qty > (line.rejected_quantity or 0):
                self.add_error(
                    'quantity',
                    f'Only {line.rejected_quantity} were rejected on that line.')
        return cleaned


# ---------- RTV lifecycle action forms ----------

class ShipRTVForm(forms.Form):
    carrier = forms.CharField(max_length=120, required=False)
    tracking_number = forms.CharField(max_length=120, required=False)


class CancelRTVForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 2,
                                     'placeholder': 'Why are you cancelling this return?'}),
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason

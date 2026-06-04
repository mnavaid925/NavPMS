"""Module 12 forms: shipment (ASN) header, shipment lines, tracking events,
delivery confirmation, backorders, documents and the cancel action.

Mirrors the purchase_orders form style: a ``tenant=`` kwarg scopes FK dropdowns to
the current tenant, ``date``/``datetime`` widgets drive the date fields, file uploads
are whitelisted by extension + size, and lightweight ``forms.Form`` classes back the
lifecycle actions. ``ShipmentLineForm`` enforces the split-delivery over-ship guard.
"""
from django import forms

from apps.purchase_orders.models import (
    PO_DISPATCHED_STATUSES,
    PO_RECEIVABLE_STATUSES,
    PurchaseOrder,
    PurchaseOrderLine,
)

from .models import (
    RECEIVED_CONDITION_CHOICES,
    Backorder,
    Shipment,
    ShipmentDocument,
    ShipmentLine,
    ShipmentTrackingEvent,
)

# Manual tracking status codes (map to a shipment-status advance in services).
MANUAL_TRACKING_STATUS_CHOICES = [
    ('picked_up', 'Picked up'),
    ('in_transit', 'In transit'),
    ('out_for_delivery', 'Out for delivery'),
    ('delivered', 'Delivered'),
    ('exception', 'Exception'),
    ('info', 'Informational'),
]


# ---------- Shipment (ASN) header ----------

class ShipmentForm(forms.ModelForm):
    class Meta:
        model = Shipment
        fields = [
            'purchase_order', 'carrier', 'carrier_code', 'service_level',
            'tracking_number', 'freight_cost', 'ship_date', 'estimated_delivery_date',
            'packing_slip_number', 'package_count', 'total_weight', 'weight_uom',
            'packing_note', 'notes',
        ]
        widgets = {
            'ship_date': forms.DateInput(attrs={'type': 'date'}),
            'estimated_delivery_date': forms.DateInput(attrs={'type': 'date'}),
            'freight_cost': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'total_weight': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'package_count': forms.NumberInput(attrs={'min': 1, 'step': 1}),
            'packing_note': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, tenant=None, vendor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.vendor = vendor
        for f in ('carrier', 'carrier_code', 'service_level', 'tracking_number',
                  'packing_slip_number', 'packing_note', 'notes'):
            self.fields[f].required = False
        self.fields['carrier_code'].help_text = (
            'Connector key for live tracking (e.g. "mock").'
        )
        # The parent PO is fixed once the shipment exists.
        if self.instance and self.instance.pk:
            self.fields['purchase_order'].disabled = True
        if tenant is not None:
            qs = PurchaseOrder.objects.filter(
                tenant=tenant, status__in=PO_DISPATCHED_STATUSES,
            ).exclude(vendor__isnull=True)
            # A supplier creating an ASN only sees their own dispatched POs.
            if vendor is not None:
                qs = qs.filter(vendor=vendor)
            self.fields['purchase_order'].queryset = qs.order_by(
                '-issued_at', '-created_at')

    def clean(self):
        cleaned = super().clean()
        ship_date = cleaned.get('ship_date')
        eta = cleaned.get('estimated_delivery_date')
        if ship_date and eta and eta < ship_date:
            self.add_error(
                'estimated_delivery_date',
                'Estimated delivery cannot be before the ship date.',
            )
        return cleaned


# ---------- Shipment line ----------

class ShipmentLineForm(forms.ModelForm):
    class Meta:
        model = ShipmentLine
        fields = [
            'purchase_order_line', 'shipped_quantity', 'carton_reference',
            'package_no', 'notes',
        ]
        widgets = {
            'shipped_quantity': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'notes': forms.TextInput(),
        }

    def __init__(self, *args, tenant=None, shipment=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.shipment = shipment
        for f in ('carton_reference', 'package_no', 'notes'):
            self.fields[f].required = False
        self.fields['purchase_order_line'].label = 'PO line'
        if shipment is not None:
            self.fields['purchase_order_line'].queryset = (
                shipment.purchase_order.lines.exclude(delivery_status='cancelled')
            )

    def clean(self):
        cleaned = super().clean()
        pol = cleaned.get('purchase_order_line')
        qty = cleaned.get('shipped_quantity')
        if pol and qty is not None:
            # Split-delivery guard: cannot ship more of a PO line than remains.
            from .services import remaining_to_ship_line
            remaining = remaining_to_ship_line(pol, exclude_shipment_line=self.instance)
            if qty <= 0:
                self.add_error('shipped_quantity', 'Quantity must be greater than zero.')
            elif qty > remaining:
                self.add_error(
                    'shipped_quantity',
                    f'Only {remaining} of PO line {pol.line_no} remains to ship.',
                )
        # `shipment` is set in the view (excluded here), so ModelForm.validate_unique
        # skips the (shipment, purchase_order_line) constraint — re-check it ourselves
        # to avoid an IntegrityError 500 (see lessons.md).
        if pol and self.shipment is not None:
            dup = ShipmentLine.all_objects.filter(
                shipment=self.shipment, purchase_order_line=pol)
            if self.instance.pk:
                dup = dup.exclude(pk=self.instance.pk)
            if dup.exists():
                self.add_error(
                    'purchase_order_line', 'This PO line is already on the shipment.')
        return cleaned


# ---------- Manual tracking event ----------

class TrackingEventForm(forms.ModelForm):
    status_code = forms.ChoiceField(choices=MANUAL_TRACKING_STATUS_CHOICES)

    class Meta:
        model = ShipmentTrackingEvent
        fields = ['status_code', 'description', 'location', 'occurred_at']
        widgets = {
            'occurred_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'description': forms.TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        self.fields['location'].required = False
        self.fields['occurred_at'].required = False


# ---------- Delivery confirmation ----------

class ConfirmDeliveryForm(forms.Form):
    delivered_at = forms.DateTimeField(
        required=False, label='Delivered at',
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text='Defaults to now.',
    )
    received_condition = forms.ChoiceField(
        choices=RECEIVED_CONDITION_CHOICES, initial='good',
    )
    post_receipt = forms.BooleanField(
        required=False, initial=True, label='Post receipts to the purchase order',
        help_text='Updates the PO line received quantities and rolls the PO status up.',
    )
    note = forms.CharField(
        required=False, max_length=255,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional delivery note'}),
    )


# ---------- Backorder ----------

class BackorderForm(forms.ModelForm):
    class Meta:
        model = Backorder
        fields = ['purchase_order_line', 'quantity', 'expected_date', 'reason']
        widgets = {
            'quantity': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'expected_date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, tenant=None, purchase_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['reason'].required = False
        self.fields['purchase_order_line'].label = 'PO line'
        if purchase_order is not None:
            self.fields['purchase_order_line'].queryset = (
                purchase_order.lines.exclude(delivery_status='cancelled')
            )
        elif tenant is not None:
            self.fields['purchase_order_line'].queryset = (
                PurchaseOrderLine.objects.filter(
                    tenant=tenant,
                    purchase_order__status__in=PO_RECEIVABLE_STATUSES,
                ).exclude(delivery_status='cancelled')
            )

    def clean_quantity(self):
        qty = self.cleaned_data.get('quantity')
        if qty is None or qty <= 0:
            raise forms.ValidationError('Backorder quantity must be greater than zero.')
        return qty


# ---------- Documents ----------

class ShipmentDocumentForm(forms.ModelForm):
    ALLOWED_EXTENSIONS = (
        'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt',
        'png', 'jpg', 'jpeg', 'zip',
    )

    class Meta:
        model = ShipmentDocument
        fields = ['title', 'doc_type', 'file', 'notes']
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

class CancelShipmentForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 2,
                                     'placeholder': 'Why are you cancelling this shipment?'}),
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason

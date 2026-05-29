"""Module 8 forms: auction setup, lots, invites, documents, bidding, award.

Mirrors the Sourcing module's form style: a ``tenant=`` kwarg scopes FK
dropdowns (category / account_code) to the current tenant, ``datetime-local``
widgets drive the schedule fields, and lightweight ``forms.Form`` classes back
the lifecycle actions (invite / cancel / place-bid / finalize).
"""
from decimal import Decimal

from django import forms

from apps.vendors.models import Vendor

from .models import Auction, AuctionDocument, AuctionLot


# ---------- Auction setup ----------

class AuctionForm(forms.ModelForm):
    class Meta:
        model = Auction
        fields = [
            'title', 'description', 'auction_type', 'category', 'currency',
            'starting_price', 'reserve_price', 'decrement_type', 'decrement_value',
            'start_at', 'end_at', 'anti_snipe_seconds', 'anti_snipe_extension_seconds',
            'max_extensions', 'rank_visibility', 'terms_and_conditions',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'terms_and_conditions': forms.Textarea(attrs={'rows': 4}),
            'start_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'end_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'starting_price': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'reserve_price': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'decrement_value': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'anti_snipe_seconds': forms.NumberInput(attrs={'min': 0, 'step': 1}),
            'anti_snipe_extension_seconds': forms.NumberInput(attrs={'min': 0, 'step': 1}),
            'max_extensions': forms.NumberInput(attrs={'min': 0, 'step': 1}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant is not None:
            from apps.vendors.models import VendorCategory
            self.fields['category'].queryset = VendorCategory.objects.filter(
                tenant=tenant, is_active=True,
            )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_at')
        end = cleaned.get('end_at')
        if start and end and end <= start:
            raise forms.ValidationError('End time must be after the start time.')

        decrement_value = cleaned.get('decrement_value')
        if decrement_value is not None and decrement_value <= Decimal('0'):
            self.add_error(
                'decrement_value', 'Decrement value must be greater than zero.',
            )

        starting = cleaned.get('starting_price')
        reserve = cleaned.get('reserve_price')
        if (reserve is not None and starting is not None
                and reserve > starting):
            self.add_error(
                'reserve_price', 'Reserve price cannot exceed the starting price.',
            )
        return cleaned


# ---------- Auction lot (basket line) ----------

class AuctionLotForm(forms.ModelForm):
    class Meta:
        model = AuctionLot
        fields = [
            'lot_no', 'title', 'item_description', 'uom', 'quantity',
            'est_unit_price', 'account_code', 'notes',
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
            'quantity': forms.NumberInput(attrs={'min': 0, 'step': '0.001'}),
            'est_unit_price': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'lot_no': forms.NumberInput(attrs={'min': 1, 'step': 1}),
        }

    def __init__(self, *args, tenant=None, auction=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.auction = auction
        if tenant is not None:
            from apps.requisitions.models import AccountCode
            self.fields['account_code'].queryset = AccountCode.objects.filter(
                tenant=tenant, is_active=True,
            )

    def clean_lot_no(self):
        lot_no = self.cleaned_data.get('lot_no') or 1
        if self.auction:
            qs = AuctionLot.all_objects.filter(
                auction=self.auction, lot_no=lot_no,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f'Lot #{lot_no} already exists on this auction.'
                )
        return lot_no


# ---------- Invitee picks ----------

class InviteVendorsForm(forms.Form):
    vendors = forms.ModelMultipleChoiceField(
        queryset=Vendor.objects.none(),
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, tenant=None, auction=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant is None:
            return
        existing = (
            auction.participants.values_list('vendor_id', flat=True)
            if auction else []
        )
        qs = Vendor.objects.filter(
            tenant=tenant,
        ).exclude(
            status__in=('suspended', 'blacklisted', 'inactive'),
        ).exclude(pk__in=existing).order_by('legal_name')
        self.fields['vendors'].queryset = qs


# ---------- Documents ----------

class AuctionDocumentForm(forms.ModelForm):
    ALLOWED_EXTENSIONS = (
        'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt',
        'png', 'jpg', 'jpeg', 'zip',
    )

    class Meta:
        model = AuctionDocument
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


# ---------- Place bid (no-JS fallback) ----------

class PlaceBidForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2,
        min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
    )


# ---------- Cancel auction ----------

class CancelAuctionForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 2,
                                     'placeholder': 'Why are you cancelling this auction?'}),
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason


# ---------- Finalize award ----------

class FinalizeAwardForm(forms.Form):
    winner_vendor = forms.ModelChoiceField(
        queryset=Vendor.objects.none(),
        required=False,
        help_text='Leave blank to award the lowest valid bid automatically.',
    )
    notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3,
                                     'placeholder': 'Award notes (optional).'}),
        required=False,
    )

    def __init__(self, *args, auction=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.auction = auction
        if auction is not None:
            vendor_ids = list(
                auction.participants.filter(
                    current_bid_amount__isnull=False,
                ).values_list('vendor_id', flat=True)
            )
            self.fields['winner_vendor'].queryset = Vendor.objects.filter(
                pk__in=vendor_ids,
            )

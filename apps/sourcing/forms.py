"""Module 6 forms: events, items, criteria, invitee picks, bids, evaluations, awards."""
from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.vendors.models import Vendor

from .models import (
    Bid, BidDocument, BidEvaluation, BidLine, SourcingAward,
    SourcingCriterion, SourcingEvent, SourcingEventItem,
)


# ---------- Event ----------

class SourcingEventForm(forms.ModelForm):
    class Meta:
        model = SourcingEvent
        fields = [
            'title', 'description', 'event_type', 'category', 'currency',
            'estimated_value', 'publish_at', 'close_at', 'award_target_at',
            'terms_and_conditions', 'allow_partial_award',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'terms_and_conditions': forms.Textarea(attrs={'rows': 4}),
            'publish_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'close_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'award_target_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'estimated_value': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
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
        publish = cleaned.get('publish_at')
        close = cleaned.get('close_at')
        if publish and close and close <= publish:
            raise forms.ValidationError('Close date must be after publish date.')
        return cleaned


# ---------- Event item ----------

class SourcingEventItemForm(forms.ModelForm):
    class Meta:
        model = SourcingEventItem
        fields = [
            'line_no', 'item_description', 'uom', 'quantity',
            'est_unit_price', 'account_code', 'required_date', 'notes',
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
            'required_date': forms.DateInput(attrs={'type': 'date'}),
            'quantity': forms.NumberInput(attrs={'min': 0, 'step': '0.001'}),
            'est_unit_price': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'line_no': forms.NumberInput(attrs={'min': 1, 'step': 1}),
        }

    def __init__(self, *args, tenant=None, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.event = event
        if tenant is not None:
            from apps.requisitions.models import AccountCode
            self.fields['account_code'].queryset = AccountCode.objects.filter(
                tenant=tenant, is_active=True,
            )

    def clean_line_no(self):
        line_no = self.cleaned_data.get('line_no') or 1
        if self.event:
            qs = SourcingEventItem.all_objects.filter(
                event=self.event, line_no=line_no,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f'Line #{line_no} already exists on this event.'
                )
        return line_no


# ---------- Criterion ----------

class SourcingCriterionForm(forms.ModelForm):
    class Meta:
        model = SourcingCriterion
        fields = [
            'name', 'criterion_type', 'weight', 'max_score', 'order', 'description',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'weight': forms.NumberInput(attrs={'min': 0, 'max': 100, 'step': '0.01'}),
            'max_score': forms.NumberInput(attrs={'min': 1, 'step': '0.01'}),
            'order': forms.NumberInput(attrs={'min': 0, 'step': 1}),
        }

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = event

    def clean_weight(self):
        weight = self.cleaned_data.get('weight') or Decimal('0')
        if weight < 0 or weight > Decimal('100'):
            raise forms.ValidationError('Weight must be between 0 and 100.')
        if self.event:
            existing = self.event.criteria.exclude(
                pk=self.instance.pk if self.instance.pk else 0,
            )
            existing_sum = sum((c.weight or Decimal('0')) for c in existing)
            if existing_sum + weight > Decimal('100'):
                raise forms.ValidationError(
                    f'Adding {weight} would push total weight above 100 '
                    f'(currently {existing_sum}).'
                )
        return weight


# ---------- Invitee picks ----------

class InviteVendorsForm(forms.Form):
    vendors = forms.ModelMultipleChoiceField(
        queryset=Vendor.objects.none(),
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, tenant=None, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant is None:
            return
        existing = (
            event.invitees.values_list('vendor_id', flat=True)
            if event else []
        )
        qs = Vendor.objects.filter(
            tenant=tenant,
        ).exclude(
            status__in=('suspended', 'blacklisted', 'inactive'),
        ).exclude(pk__in=existing).order_by('legal_name')
        self.fields['vendors'].queryset = qs


# ---------- Cancel event ----------

class CancelEventForm(forms.Form):
    reason = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 2,
                                     'placeholder': 'Why are you cancelling this event?'}),
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Please give a reason.')
        return reason


# ---------- Bid (vendor side) ----------

class BidForm(forms.ModelForm):
    class Meta:
        model = Bid
        fields = [
            'delivery_lead_time_days', 'validity_days', 'payment_terms', 'notes',
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
            'delivery_lead_time_days': forms.NumberInput(attrs={'min': 0, 'step': 1}),
            'validity_days': forms.NumberInput(attrs={'min': 0, 'step': 1}),
        }


class BidLineForm(forms.ModelForm):
    class Meta:
        model = BidLine
        fields = ['unit_price', 'quantity_offered', 'lead_time_days', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
            'unit_price': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'quantity_offered': forms.NumberInput(attrs={'min': 0, 'step': '0.001'}),
            'lead_time_days': forms.NumberInput(attrs={'min': 0, 'step': 1}),
        }


class BidDocumentForm(forms.ModelForm):
    class Meta:
        model = BidDocument
        fields = ['title', 'file', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}

    def clean_file(self):
        f = self.cleaned_data.get('file')
        if f:
            if f.size > 10 * 1024 * 1024:
                raise forms.ValidationError('File size must be 10 MB or less.')
        return f


# ---------- Bid evaluation (buyer side) ----------

class BidEvaluationForm(forms.ModelForm):
    class Meta:
        model = BidEvaluation
        fields = ['score', 'comment']
        widgets = {
            'score': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'comment': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, criterion=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.criterion = criterion
        if criterion:
            self.fields['score'].widget.attrs['max'] = str(criterion.max_score)
            self.fields['score'].help_text = f'0 – {criterion.max_score}'

    def clean_score(self):
        score = self.cleaned_data.get('score') or Decimal('0')
        if self.criterion and (score < 0 or score > self.criterion.max_score):
            raise forms.ValidationError(
                f'Score must be between 0 and {self.criterion.max_score}.'
            )
        return score


# ---------- Award recommendation ----------

class AwardRecommendForm(forms.Form):
    vendor = forms.ModelChoiceField(queryset=Vendor.objects.none())
    award_amount = forms.DecimalField(
        max_digits=14, decimal_places=2,
        widget=forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
    )
    justification = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3,
                                     'placeholder': 'Why this vendor?'}),
        required=False,
    )

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = event
        if event is not None:
            vendor_ids = list(
                event.bids.exclude(status='withdrawn')
                          .values_list('vendor_id', flat=True)
            )
            self.fields['vendor'].queryset = Vendor.objects.filter(
                pk__in=vendor_ids,
            )

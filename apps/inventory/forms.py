"""Module 19 forms: warehouses, locations, stock items, manual adjustments, goods issues, cycle counts.

A ``tenant=`` kwarg scopes every FK dropdown to the current tenant (warehouses, locations, catalog
items, stock items), mirroring the budget / compliance style.
"""
from decimal import Decimal

from django import forms

from apps.catalog.models import CatalogItem

from .models import (
    CYCLE_SCOPE_CHOICES, CycleCount, GoodsIssue, ISSUE_TYPE_CHOICES, StockItem, Warehouse,
    WarehouseLocation,
)


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ['code', 'name', 'address', 'is_active', 'is_default']
        widgets = {'address': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['address'].required = False


class WarehouseLocationForm(forms.ModelForm):
    class Meta:
        model = WarehouseLocation
        fields = ['warehouse', 'code', 'aisle', 'rack', 'shelf', 'description', 'is_active']

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        for name in ('aisle', 'rack', 'shelf', 'description'):
            self.fields[name].required = False
        if tenant is not None:
            self.fields['warehouse'].queryset = Warehouse.objects.filter(
                tenant=tenant).order_by('code')


class StockItemForm(forms.ModelForm):
    """Edit a stock item's inventory parameters (the catalog link is fixed)."""

    class Meta:
        model = StockItem
        fields = ['is_stocked', 'default_warehouse', 'default_location', 'reorder_point',
                  'reorder_quantity', 'safety_stock', 'lead_time_days', 'abc_class']

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['default_warehouse'].required = False
        self.fields['default_location'].required = False
        self.fields['abc_class'].required = False
        if tenant is not None:
            self.fields['default_warehouse'].queryset = Warehouse.objects.filter(
                tenant=tenant).order_by('code')
            self.fields['default_location'].queryset = WarehouseLocation.objects.filter(
                tenant=tenant).select_related('warehouse').order_by('warehouse__code', 'code')


class StockItemCreateForm(StockItemForm):
    """Create a stock item by picking an approved catalog item not yet tracked."""

    catalog_item = forms.ModelChoiceField(queryset=CatalogItem.objects.none(), label='Catalog item')

    field_order = ['catalog_item', 'is_stocked', 'default_warehouse', 'default_location',
                   'reorder_point', 'reorder_quantity', 'safety_stock', 'lead_time_days',
                   'abc_class']

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, tenant=tenant, **kwargs)
        if tenant is not None:
            tracked = StockItem.objects.filter(tenant=tenant).values_list(
                'catalog_item_id', flat=True)
            self.fields['catalog_item'].queryset = CatalogItem.objects.filter(
                tenant=tenant, status='approved').exclude(pk__in=tracked).order_by('name')


class StockAdjustForm(forms.Form):
    """Record a manual signed stock adjustment against a bucket."""

    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none())
    location = forms.ModelChoiceField(queryset=WarehouseLocation.objects.none(), required=False)
    quantity = forms.DecimalField(
        max_digits=12, decimal_places=2,
        help_text='Signed: positive adds stock, negative removes it.')
    lot_number = forms.CharField(max_length=80, required=False)
    serial_number = forms.CharField(max_length=120, required=False)
    expiry_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    reason = forms.CharField(max_length=120, required=False)
    note = forms.CharField(max_length=255, required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant is not None:
            self.fields['warehouse'].queryset = Warehouse.objects.filter(
                tenant=tenant, is_active=True).order_by('code')
            self.fields['location'].queryset = WarehouseLocation.objects.filter(
                tenant=tenant).select_related('warehouse').order_by('warehouse__code', 'code')

    def clean_quantity(self):
        qty = self.cleaned_data['quantity']
        if qty == Decimal('0'):
            raise forms.ValidationError('Enter a non-zero adjustment quantity.')
        return qty


class GoodsIssueForm(forms.ModelForm):
    class Meta:
        model = GoodsIssue
        fields = ['warehouse', 'issue_type', 'purpose', 'department', 'cost_center', 'note']
        widgets = {'note': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        for name in ('purpose', 'department', 'cost_center', 'note'):
            self.fields[name].required = False
        if tenant is not None:
            self.fields['warehouse'].queryset = Warehouse.objects.filter(
                tenant=tenant, is_active=True).order_by('code')


class GoodsIssueLineForm(forms.Form):
    """Add a line to a draft goods issue."""

    stock_item = forms.ModelChoiceField(queryset=StockItem.objects.none())
    location = forms.ModelChoiceField(queryset=WarehouseLocation.objects.none(), required=False)
    quantity = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    lot_number = forms.CharField(max_length=80, required=False)
    serial_number = forms.CharField(max_length=120, required=False)
    expiry_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    note = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant is not None:
            self.fields['stock_item'].queryset = StockItem.objects.filter(
                tenant=tenant).select_related('catalog_item').order_by('catalog_item__name')
            self.fields['location'].queryset = WarehouseLocation.objects.filter(
                tenant=tenant).select_related('warehouse').order_by('warehouse__code', 'code')


class CycleCountForm(forms.ModelForm):
    class Meta:
        model = CycleCount
        fields = ['warehouse', 'scope', 'scheduled_date', 'note']
        widgets = {
            'scheduled_date': forms.DateInput(attrs={'type': 'date'}),
            'note': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['scheduled_date'].required = False
        self.fields['note'].required = False
        if tenant is not None:
            self.fields['warehouse'].queryset = Warehouse.objects.filter(
                tenant=tenant, is_active=True).order_by('code')

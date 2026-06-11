"""Global header search — a declarative registry of searchable entities.

The topbar search box submits a query (``?q=``) to ``core:search``
(:class:`apps.core.views.GlobalSearchView`). That view walks this registry, runs a
tenant-scoped ``icontains`` OR across each spec's ``fields``, and links every hit to
its detail page. Adding a new searchable entity = append one :class:`SearchSpec`.

Only entities with a tenant FK and a named single-``<int:pk>`` detail route belong here
(nested/child routes that need a parent pk can't be reversed from a single pk).
"""
from dataclasses import dataclass

from django.apps import apps as django_apps


@dataclass(frozen=True)
class SearchSpec:
    label: str            # human label, e.g. "Purchase Order"
    model: str            # "app_label.Model" — resolved lazily via apps.get_model
    fields: tuple         # text fields OR'd together with __icontains
    number_field: str     # primary identifier shown in a result row
    url_name: str         # namespaced detail route, reversed with kwargs={'pk': obj.pk}
    icon: str             # remixicon class
    title_field: str = ''  # secondary descriptor ('' if the model has none)
    order: str = '-id'     # ordering applied before the per-type cap

    def get_model(self):
        return django_apps.get_model(self.model)


# Order here is the order groups appear on the results page — most-used first.
SEARCH_REGISTRY = [
    SearchSpec(
        label='Requisition', model='requisitions.Requisition',
        fields=('number', 'title'), number_field='number', title_field='title',
        url_name='requisitions:requisition_detail', order='-created_at',
        icon='ri-file-list-3-line',
    ),
    SearchSpec(
        label='Purchase Order', model='purchase_orders.PurchaseOrder',
        fields=('po_number', 'title', 'description'),
        number_field='po_number', title_field='title',
        url_name='purchase_orders:po_detail', order='-created_at',
        icon='ri-shopping-bag-3-line',
    ),
    SearchSpec(
        label='Goods Receipt', model='goods_receipt.GoodsReceipt',
        fields=('grn_number', 'delivery_note_ref', 'warehouse_location'),
        number_field='grn_number', title_field='delivery_note_ref',
        url_name='goods_receipt:grn_detail', order='-created_at',
        icon='ri-inbox-archive-line',
    ),
    SearchSpec(
        label='Return to Vendor', model='goods_receipt.ReturnToVendor',
        fields=('rtv_number', 'rma_number'),
        number_field='rtv_number', title_field='rma_number',
        url_name='goods_receipt:rtv_detail', order='-created_at',
        icon='ri-reply-line',
    ),
    SearchSpec(
        label='Shipment', model='fulfillment.Shipment',
        fields=('shipment_number', 'packing_slip_number', 'tracking_number'),
        number_field='shipment_number', title_field='tracking_number',
        url_name='fulfillment:shipment_detail', order='-created_at',
        icon='ri-truck-line',
    ),
    SearchSpec(
        label='Supplier Invoice', model='invoicing.SupplierInvoice',
        fields=('invoice_number', 'supplier_invoice_ref'),
        number_field='invoice_number', title_field='supplier_invoice_ref',
        url_name='invoicing:invoice_detail', order='-created_at',
        icon='ri-bill-line',
    ),
    SearchSpec(
        label='Payment Voucher', model='invoicing.PaymentVoucher',
        fields=('voucher_number', 'reference'),
        number_field='voucher_number', title_field='reference',
        url_name='invoicing:voucher_detail', order='-created_at',
        icon='ri-money-dollar-circle-line',
    ),
    SearchSpec(
        label='Contract', model='contracts.Contract',
        fields=('contract_number', 'title', 'description'),
        number_field='contract_number', title_field='title',
        url_name='contracts:contract_detail', order='-created_at',
        icon='ri-file-paper-2-line',
    ),
    SearchSpec(
        label='RFx Event', model='rfx.RfxEvent',
        fields=('event_number', 'title', 'description'),
        number_field='event_number', title_field='title',
        url_name='rfx:event_detail', order='-created_at',
        icon='ri-mail-send-line',
    ),
    SearchSpec(
        label='Sourcing Event', model='sourcing.SourcingEvent',
        fields=('event_number', 'title', 'description'),
        number_field='event_number', title_field='title',
        url_name='sourcing:event_detail', order='-created_at',
        icon='ri-focus-2-line',
    ),
    SearchSpec(
        label='Auction', model='auctions.Auction',
        fields=('auction_number', 'title', 'description'),
        number_field='auction_number', title_field='title',
        url_name='auctions:auction_detail', order='-created_at',
        icon='ri-auction-line',
    ),
    SearchSpec(
        label='Vendor', model='vendors.Vendor',
        fields=('vendor_number', 'legal_name', 'trade_name', 'tax_id',
                'registration_number'),
        number_field='vendor_number', title_field='legal_name',
        url_name='vendors:vendor_detail', order='-created_at',
        icon='ri-building-2-line',
    ),
    SearchSpec(
        label='Onboarding Application', model='vendors.VendorOnboardingApplication',
        fields=('company_name', 'trade_name', 'contact_email', 'tax_id',
                'registration_number'),
        number_field='company_name', title_field='contact_email',
        url_name='vendors:onboarding_detail', order='-submitted_at',
        icon='ri-user-add-line',
    ),
    SearchSpec(
        label='Catalog Item', model='catalog.CatalogItem',
        fields=('item_number', 'name', 'description', 'sku',
                'manufacturer_part_number', 'keywords'),
        number_field='item_number', title_field='name',
        url_name='catalog:item_detail', order='-created_at',
        icon='ri-price-tag-3-line',
    ),
    SearchSpec(
        label='Warehouse', model='inventory.Warehouse',
        fields=('code', 'name'), number_field='code', title_field='name',
        url_name='inventory:warehouse_detail', order='-id',
        icon='ri-building-4-line',
    ),
    SearchSpec(
        label='Stock Item', model='inventory.StockItem',
        fields=('sku',), number_field='sku',
        url_name='inventory:stock_item_detail', order='-created_at',
        icon='ri-archive-line',
    ),
    SearchSpec(
        label='Document', model='dms.Document',
        fields=('document_number', 'title', 'summary', 'tags'),
        number_field='document_number', title_field='title',
        url_name='dms:document_detail', order='-created_at',
        icon='ri-file-document-line',
    ),
]

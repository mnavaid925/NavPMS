"""Vendor Portal URLs — separate shell mounted at /vendor-portal/.

Routes are gated by the `@vendor_required` decorator inside the views, so a
non-vendor user hitting any of these gets bounced back to the dashboard.
"""
from django.urls import path

from . import views
from apps.sourcing import portal_views as sourcing_portal
from apps.rfx import portal_views as rfx_portal
from apps.auctions import portal_views as auctions_portal
from apps.contracts import portal_views as contracts_portal
from apps.catalog import portal_views as catalog_portal
from apps.purchase_orders import portal_views as po_portal
from apps.fulfillment import portal_views as fulfillment_portal
from apps.goods_receipt import portal_views as goods_receipt_portal
from apps.invoicing import portal_views as invoicing_portal
from apps.supplier_performance import portal_views as performance_portal

app_name = 'vendor_portal'

urlpatterns = [
    path('', views.portal_dashboard, name='dashboard'),
    path('profile/', views.portal_profile, name='profile'),
    path('profile/edit/', views.portal_profile_edit, name='profile_edit'),
    path('documents/', views.portal_documents, name='documents'),
    path('contacts/', views.portal_contacts, name='contacts'),
    path('purchase-orders/', po_portal.portal_po_list, name='purchase_orders'),
    path('purchase-orders/<int:pk>/', po_portal.portal_po_detail,
         name='purchase_order_detail'),
    path('purchase-orders/<int:pk>/acknowledge/', po_portal.portal_po_acknowledge,
         name='purchase_order_acknowledge'),
    path('purchase-orders/<int:pk>/decline/', po_portal.portal_po_decline,
         name='purchase_order_decline'),
    # Module 14 — Invoice & Voucher Management (vendor-side: submit + dispute)
    path('invoices/', invoicing_portal.portal_invoice_list, name='invoices'),
    path('invoices/new/', invoicing_portal.portal_invoice_create, name='invoice_create'),
    path('invoices/<int:pk>/', invoicing_portal.portal_invoice_detail,
         name='invoice_detail'),
    path('invoices/<int:pk>/reply/', invoicing_portal.portal_dispute_reply,
         name='invoice_dispute_reply'),

    # Module 6 — Sourcing & Tendering (vendor-side)
    path('sourcing/', sourcing_portal.portal_invitations,
         name='sourcing_invitations'),
    path('sourcing/<int:event_pk>/', sourcing_portal.portal_event_detail,
         name='sourcing_event_detail'),
    path('sourcing/<int:event_pk>/bid/start/', sourcing_portal.portal_bid_start,
         name='sourcing_bid_start'),
    path('sourcing/<int:event_pk>/bid/<int:bpk>/', sourcing_portal.portal_bid_edit,
         name='sourcing_bid_edit'),
    path('sourcing/<int:event_pk>/bid/<int:bpk>/submit/',
         sourcing_portal.portal_bid_submit, name='sourcing_bid_submit'),
    path('sourcing/<int:event_pk>/bid/<int:bpk>/withdraw/',
         sourcing_portal.portal_bid_withdraw, name='sourcing_bid_withdraw'),
    path('sourcing/<int:event_pk>/bid/<int:bpk>/view/',
         sourcing_portal.portal_bid_detail, name='sourcing_bid_detail'),
    path('sourcing/invitations/<int:ipk>/decline/',
         sourcing_portal.portal_invitation_decline,
         name='sourcing_invitation_decline'),
    path('sourcing/bids/', sourcing_portal.portal_my_bids, name='sourcing_my_bids'),

    # Module 7 — RFx Management (vendor-side)
    path('rfx/', rfx_portal.portal_invitations, name='rfx_inbox'),
    path('rfx/<int:event_pk>/', rfx_portal.portal_event_view, name='rfx_event'),
    path('rfx/<int:event_pk>/response/start/',
         rfx_portal.portal_response_start, name='rfx_response_start'),
    path('rfx/<int:event_pk>/response/<int:rpk>/',
         rfx_portal.portal_response_edit, name='rfx_response_edit'),
    path('rfx/<int:event_pk>/response/<int:rpk>/submit/',
         rfx_portal.portal_response_submit, name='rfx_response_submit'),
    path('rfx/<int:event_pk>/response/<int:rpk>/withdraw/',
         rfx_portal.portal_response_withdraw, name='rfx_response_withdraw'),
    path('rfx/invitations/<int:ipk>/decline/',
         rfx_portal.portal_invitation_decline, name='rfx_invitation_decline'),
    path('rfx/responses/', rfx_portal.portal_my_responses, name='rfx_my_responses'),

    # Module 8 — E-Auction Management (vendor-side)
    path('auctions/', auctions_portal.portal_auction_list,
         name='auction_invitations'),
    path('auctions/<int:pk>/', auctions_portal.portal_auction_detail,
         name='auction_event_detail'),
    path('auctions/<int:pk>/accept/', auctions_portal.portal_accept,
         name='auction_accept'),
    path('auctions/<int:pk>/decline/', auctions_portal.portal_decline,
         name='auction_decline'),
    path('auctions/<int:pk>/withdraw/', auctions_portal.portal_withdraw,
         name='auction_withdraw'),
    path('auctions/<int:pk>/bidding/', auctions_portal.portal_bidding,
         name='auction_bidding'),
    path('auctions/<int:pk>/state/', auctions_portal.portal_state,
         name='auction_state'),
    path('auctions/<int:pk>/place-bid/', auctions_portal.portal_place_bid,
         name='auction_place_bid'),

    # Module 9 — Contract Management (vendor-side)
    path('contracts/', contracts_portal.portal_contract_list,
         name='contract_inbox'),
    path('contracts/<int:pk>/', contracts_portal.portal_contract_detail,
         name='contract_detail'),
    path('sign/<str:token>/', contracts_portal.portal_sign,
         name='contract_sign'),
    path('sign/<str:token>/decline/', contracts_portal.portal_sign_decline,
         name='contract_sign_decline'),

    # Module 12 — Order Fulfillment & Tracking (vendor-side: ASN)
    path('shipments/', fulfillment_portal.portal_shipment_list, name='shipments'),
    path('shipments/new/', fulfillment_portal.portal_asn_create, name='asn_create'),
    path('shipments/<int:pk>/', fulfillment_portal.portal_shipment_detail,
         name='shipment_detail'),
    path('shipments/<int:pk>/edit/', fulfillment_portal.portal_asn_edit,
         name='asn_edit'),
    path('shipments/<int:pk>/advise/', fulfillment_portal.portal_asn_advise,
         name='asn_advise'),
    path('shipments/<int:pk>/lines/add/', fulfillment_portal.portal_asn_line_add,
         name='asn_line_add'),
    path('shipments/<int:pk>/lines/<int:line_pk>/edit/',
         fulfillment_portal.portal_asn_line_edit, name='asn_line_edit'),
    path('shipments/<int:pk>/lines/<int:line_pk>/delete/',
         fulfillment_portal.portal_asn_line_delete, name='asn_line_delete'),

    # Module 13 — Goods Receipt & Inspection (vendor-side: Return to Vendor)
    path('returns/', goods_receipt_portal.portal_rtv_list, name='returns'),
    path('returns/<int:pk>/', goods_receipt_portal.portal_rtv_detail, name='rtv_detail'),
    path('returns/<int:pk>/acknowledge/', goods_receipt_portal.portal_rtv_acknowledge,
         name='rtv_acknowledge'),

    # Module 17 — Supplier Performance & Evaluation (vendor-side: view scorecards + feedback + PIPs)
    path('performance/', performance_portal.portal_scorecards, name='performance_scorecards'),
    path('performance/<int:pk>/', performance_portal.portal_scorecard_detail,
         name='performance_scorecard_detail'),
    path('performance/feedback/', performance_portal.portal_feedback,
         name='performance_feedback'),
    path('performance/pips/', performance_portal.portal_pips, name='performance_pips'),
    path('performance/pips/<int:pk>/', performance_portal.portal_pip_detail,
         name='performance_pip_detail'),
    path('performance/pips/<int:pk>/acknowledge/', performance_portal.portal_pip_acknowledge,
         name='performance_pip_acknowledge'),

    # Module 10 — Catalog Management (vendor-side: supplier catalog hosting)
    path('catalog/', catalog_portal.portal_catalog_list, name='catalog_items'),
    path('catalog/uploads/', catalog_portal.portal_upload_list, name='catalog_uploads'),
    path('catalog/uploads/new/', catalog_portal.portal_upload_create,
         name='catalog_upload_create'),
    path('catalog/uploads/<int:pk>/', catalog_portal.portal_upload_detail,
         name='catalog_upload_detail'),
    path('catalog/uploads/<int:pk>/delete/', catalog_portal.portal_upload_delete,
         name='catalog_upload_delete'),
]

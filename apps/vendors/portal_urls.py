"""Vendor Portal URLs — separate shell mounted at /vendor-portal/.

Routes are gated by the `@vendor_required` decorator inside the views, so a
non-vendor user hitting any of these gets bounced back to the dashboard.
"""
from django.urls import path

from . import views
from apps.sourcing import portal_views as sourcing_portal
from apps.rfx import portal_views as rfx_portal
from apps.auctions import portal_views as auctions_portal

app_name = 'vendor_portal'

urlpatterns = [
    path('', views.portal_dashboard, name='dashboard'),
    path('profile/', views.portal_profile, name='profile'),
    path('profile/edit/', views.portal_profile_edit, name='profile_edit'),
    path('documents/', views.portal_documents, name='documents'),
    path('contacts/', views.portal_contacts, name='contacts'),
    path('purchase-orders/', views.portal_purchase_orders, name='purchase_orders'),
    path('invoices/', views.portal_invoices, name='invoices'),

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
]

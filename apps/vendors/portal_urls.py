"""Vendor Portal URLs — separate shell mounted at /vendor-portal/.

Routes are gated by the `@vendor_required` decorator inside the views, so a
non-vendor user hitting any of these gets bounced back to the dashboard.
"""
from django.urls import path

from . import views
from apps.sourcing import portal_views as sourcing_portal

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
]

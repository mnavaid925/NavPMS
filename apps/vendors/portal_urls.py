"""Vendor Portal URLs — separate shell mounted at /vendor-portal/.

Routes are gated by the `@vendor_required` decorator inside the views, so a
non-vendor user hitting any of these gets bounced back to the dashboard.
"""
from django.urls import path

from . import views

app_name = 'vendor_portal'

urlpatterns = [
    path('', views.portal_dashboard, name='dashboard'),
    path('profile/', views.portal_profile, name='profile'),
    path('profile/edit/', views.portal_profile_edit, name='profile_edit'),
    path('documents/', views.portal_documents, name='documents'),
    path('contacts/', views.portal_contacts, name='contacts'),
    path('purchase-orders/', views.portal_purchase_orders, name='purchase_orders'),
    path('invoices/', views.portal_invoices, name='invoices'),
]

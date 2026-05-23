"""Internal (tenant-side) URLs for Module 5 — Vendor Management."""
from django.urls import path

from . import views

app_name = 'vendors'

urlpatterns = [
    # Vendors
    path('', views.vendor_list, name='vendor_list'),
    path('create/', views.vendor_create, name='vendor_create'),
    path('<int:pk>/', views.vendor_detail, name='vendor_detail'),
    path('<int:pk>/edit/', views.vendor_edit, name='vendor_edit'),
    path('<int:pk>/delete/', views.vendor_delete, name='vendor_delete'),
    path('<int:pk>/verify/', views.vendor_verify, name='vendor_verify'),

    # Vendor sub-records
    path('<int:vendor_pk>/contacts/add/', views.contact_add, name='contact_add'),
    path('<int:vendor_pk>/contacts/<int:pk>/delete/', views.contact_delete, name='contact_delete'),
    path('<int:vendor_pk>/documents/add/', views.document_add, name='document_add'),
    path('<int:vendor_pk>/documents/<int:pk>/verify/', views.document_verify, name='document_verify'),
    path('<int:vendor_pk>/documents/<int:pk>/delete/', views.document_delete, name='document_delete'),
    path('<int:vendor_pk>/banks/add/', views.bank_add, name='bank_add'),
    path('<int:vendor_pk>/banks/<int:pk>/delete/', views.bank_delete, name='bank_delete'),

    # Classification
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),

    # Segmentation
    path('segments/', views.segment_list, name='segment_list'),
    path('segments/create/', views.segment_create, name='segment_create'),
    path('segments/<int:pk>/edit/', views.segment_edit, name='segment_edit'),
    path('segments/<int:pk>/delete/', views.segment_delete, name='segment_delete'),

    # Risk
    path('<int:vendor_pk>/risk/create/', views.risk_create, name='risk_create'),
    path('<int:vendor_pk>/risk/<int:pk>/', views.risk_detail, name='risk_detail'),
    path('<int:vendor_pk>/risk/<int:pk>/delete/', views.risk_delete, name='risk_delete'),

    # Onboarding (PUBLIC)
    path('onboarding/apply/<slug:tenant_slug>/', views.onboarding_apply, name='onboarding_apply'),
    path('onboarding/applied/<slug:tenant_slug>/', views.onboarding_applied, name='onboarding_applied'),
    # Onboarding admin
    path('onboarding/', views.onboarding_list, name='onboarding_list'),
    path('onboarding/<int:pk>/', views.onboarding_detail, name='onboarding_detail'),

    # Blacklist / Suspend / Reinstate
    path('<int:vendor_pk>/blacklist/', views.blacklist_action, name='blacklist_action'),
    path('blacklist/history/', views.blacklist_history, name='blacklist_history'),

    # Portal invite (admin side)
    path('<int:vendor_pk>/portal/invite/', views.portal_invite, name='portal_invite'),
    path('<int:vendor_pk>/portal/revoke/', views.portal_revoke, name='portal_revoke'),
]

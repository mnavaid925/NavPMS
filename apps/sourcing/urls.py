"""Internal (buyer-side) URLs for Module 6 — Sourcing & Tendering."""
from django.urls import path

from . import views

app_name = 'sourcing'

urlpatterns = [
    # Events
    path('events/', views.event_list, name='event_list'),
    path('events/new/', views.event_create, name='event_create'),
    path('events/<int:pk>/', views.event_detail, name='event_detail'),
    path('events/<int:pk>/edit/', views.event_edit, name='event_edit'),
    path('events/<int:pk>/delete/', views.event_delete, name='event_delete'),

    # Event lifecycle actions
    path('events/<int:pk>/publish/', views.event_publish, name='event_publish'),
    path('events/<int:pk>/open/', views.event_open, name='event_open'),
    path('events/<int:pk>/close/', views.event_close, name='event_close'),
    path('events/<int:pk>/cancel/', views.event_cancel, name='event_cancel'),

    # Event items
    path('events/<int:pk>/items/add/', views.item_create, name='item_create'),
    path('events/<int:pk>/items/<int:lpk>/edit/', views.item_edit, name='item_edit'),
    path('events/<int:pk>/items/<int:lpk>/delete/', views.item_delete, name='item_delete'),

    # Invitees
    path('events/<int:pk>/invitees/add/', views.invitee_add, name='invitee_add'),
    path('events/<int:pk>/invitees/<int:ipk>/remove/',
         views.invitee_remove, name='invitee_remove'),

    # Criteria
    path('events/<int:pk>/criteria/add/', views.criterion_create, name='criterion_create'),
    path('events/<int:pk>/criteria/<int:cpk>/edit/',
         views.criterion_edit, name='criterion_edit'),
    path('events/<int:pk>/criteria/<int:cpk>/delete/',
         views.criterion_delete, name='criterion_delete'),

    # Bids (buyer side — sealed)
    path('events/<int:pk>/bids/', views.bid_list, name='bid_list'),
    path('events/<int:pk>/bids/compare/', views.bid_compare, name='bid_compare'),
    path('events/<int:pk>/bids/<int:bpk>/', views.bid_detail, name='bid_detail'),
    path('events/<int:pk>/bids/<int:bpk>/evaluate/',
         views.bid_evaluate, name='bid_evaluate'),
    path('events/<int:pk>/bids/<int:bpk>/shortlist/',
         views.bid_shortlist, name='bid_shortlist'),
    path('events/<int:pk>/bids/<int:bpk>/reject/',
         views.bid_reject, name='bid_reject'),

    # Awards
    path('events/<int:pk>/awards/recommend/',
         views.award_recommend, name='award_recommend'),
    path('events/<int:pk>/awards/finalize/',
         views.award_finalize, name='award_finalize'),

    # Analytics
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),
    path('events/<int:pk>/analytics/', views.analytics_event_report,
         name='analytics_event_report'),
]

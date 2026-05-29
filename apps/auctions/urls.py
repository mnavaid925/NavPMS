from django.urls import path

from . import views

app_name = 'auctions'

urlpatterns = [
    # Analytics dashboard
    path('', views.analytics_dashboard, name='dashboard'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),

    # Auction list + CRUD
    path('events/', views.auction_list, name='auction_list'),
    path('events/new/', views.auction_create, name='auction_create'),
    path('events/<int:pk>/', views.auction_detail, name='auction_detail'),
    path('events/<int:pk>/edit/', views.auction_edit, name='auction_edit'),
    path('events/<int:pk>/delete/', views.auction_delete, name='auction_delete'),

    # Lifecycle transitions (POST)
    path('events/<int:pk>/publish/', views.auction_publish, name='auction_publish'),
    path('events/<int:pk>/start/', views.auction_start, name='auction_start'),
    path('events/<int:pk>/close/', views.auction_close, name='auction_close'),
    path('events/<int:pk>/cancel/', views.auction_cancel, name='auction_cancel'),

    # Lots
    path('events/<int:pk>/lots/new/', views.lot_create, name='lot_create'),
    path('events/<int:pk>/lots/<int:lot_pk>/edit/', views.lot_edit, name='lot_edit'),
    path('events/<int:pk>/lots/<int:lot_pk>/delete/', views.lot_delete, name='lot_delete'),

    # Participants
    path('events/<int:pk>/participants/add/', views.participant_add, name='participant_add'),
    path('events/<int:pk>/participants/<int:participant_pk>/remove/', views.participant_remove, name='participant_remove'),

    # Documents
    path('events/<int:pk>/documents/add/', views.document_add, name='document_add'),
    path('events/<int:pk>/documents/<int:document_pk>/delete/', views.document_delete, name='document_delete'),

    # Live console (buyer monitor)
    path('events/<int:pk>/console/', views.console, name='console'),
    path('events/<int:pk>/console/state/', views.console_state, name='console_state'),

    # Results + award
    path('events/<int:pk>/results/', views.results, name='results'),
    path('events/<int:pk>/award/', views.award_finalize, name='award_finalize'),

    # Per-auction analytics
    path('events/<int:pk>/analytics/', views.auction_analytics, name='auction_analytics'),
]

from django.urls import path

from . import views

app_name = 'fulfillment'

urlpatterns = [
    # Dashboard / analytics
    path('', views.analytics_dashboard, name='dashboard'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),

    # Tracking board
    path('tracking/', views.tracking_board, name='tracking_board'),

    # Backorders
    path('backorders/', views.backorder_board, name='backorder_board'),
    path('backorders/new/', views.backorder_create, name='backorder_create'),
    path('backorders/<int:pk>/fulfill/', views.backorder_fulfill, name='backorder_fulfill'),
    path('backorders/<int:pk>/cancel/', views.backorder_cancel, name='backorder_cancel'),

    # List + create
    path('list/', views.shipment_list, name='shipment_list'),
    path('new/', views.shipment_create, name='shipment_create'),

    # Detail + CRUD
    path('<int:pk>/', views.shipment_detail, name='shipment_detail'),
    path('<int:pk>/edit/', views.shipment_edit, name='shipment_edit'),
    path('<int:pk>/delete/', views.shipment_delete, name='shipment_delete'),

    # Lifecycle (POST)
    path('<int:pk>/advise/', views.shipment_advise, name='shipment_advise'),
    path('<int:pk>/sync-tracking/', views.shipment_sync_tracking, name='shipment_sync_tracking'),
    path('<int:pk>/tracking/add/', views.tracking_event_add, name='tracking_event_add'),
    path('<int:pk>/confirm-delivery/', views.shipment_confirm_delivery, name='shipment_confirm_delivery'),
    path('<int:pk>/cancel/', views.shipment_cancel, name='shipment_cancel'),
    path('<int:pk>/close/', views.shipment_close, name='shipment_close'),

    # Line items
    path('<int:pk>/lines/add/', views.line_add, name='line_add'),
    path('<int:pk>/lines/<int:line_pk>/edit/', views.line_edit, name='line_edit'),
    path('<int:pk>/lines/<int:line_pk>/delete/', views.line_delete, name='line_delete'),

    # Documents
    path('<int:pk>/documents/add/', views.document_add, name='document_add'),
    path('<int:pk>/documents/<int:document_pk>/delete/', views.document_delete, name='document_delete'),
]

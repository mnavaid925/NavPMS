from django.urls import path

from . import views

app_name = 'purchase_orders'

urlpatterns = [
    # Dashboard / analytics
    path('', views.analytics_dashboard, name='dashboard'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),

    # Tracking board
    path('tracking/', views.po_tracking, name='po_tracking'),

    # List + create
    path('list/', views.po_list, name='po_list'),
    path('new/', views.po_create, name='po_create'),

    # Detail + CRUD
    path('<int:pk>/', views.po_detail, name='po_detail'),
    path('<int:pk>/edit/', views.po_edit, name='po_edit'),
    path('<int:pk>/delete/', views.po_delete, name='po_delete'),

    # Lifecycle (POST)
    path('<int:pk>/issue/', views.po_issue, name='po_issue'),
    path('<int:pk>/acknowledge/', views.po_acknowledge, name='po_acknowledge'),
    path('<int:pk>/decline/', views.po_decline, name='po_decline'),
    path('<int:pk>/reopen/', views.po_reopen, name='po_reopen'),
    path('<int:pk>/cancel/', views.po_cancel, name='po_cancel'),
    path('<int:pk>/close/', views.po_close, name='po_close'),

    # Line items
    path('<int:pk>/lines/add/', views.line_add, name='line_add'),
    path('<int:pk>/lines/<int:line_pk>/edit/', views.line_edit, name='line_edit'),
    path('<int:pk>/lines/<int:line_pk>/delete/', views.line_delete, name='line_delete'),
    path('<int:pk>/lines/<int:line_pk>/receive/', views.line_receive, name='line_receive'),

    # Change orders
    path('<int:pk>/change-orders/new/', views.change_order_create, name='change_order_create'),
    path('<int:pk>/change-orders/<int:co_pk>/', views.change_order_detail, name='change_order_detail'),
    path('<int:pk>/change-orders/<int:co_pk>/apply/', views.change_order_apply, name='change_order_apply'),
    path('<int:pk>/change-orders/<int:co_pk>/cancel/', views.change_order_cancel, name='change_order_cancel'),

    # Documents
    path('<int:pk>/documents/add/', views.document_add, name='document_add'),
    path('<int:pk>/documents/<int:document_pk>/delete/', views.document_delete, name='document_delete'),
]

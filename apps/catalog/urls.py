from django.urls import path

from . import views

app_name = 'catalog'

urlpatterns = [
    # Dashboard / analytics
    path('', views.analytics_dashboard, name='dashboard'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),

    # Board
    path('approvals/', views.approval_board, name='approval_board'),

    # Item list + create
    path('items/', views.item_list, name='item_list'),
    path('items/new/', views.item_create, name='item_create'),

    # Categories
    path('categories/', views.category_list, name='category_list'),
    path('categories/new/', views.category_create, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),

    # Punch-out configuration + sessions
    path('punchout/', views.punchout_config_list, name='punchout_config_list'),
    path('punchout/new/', views.punchout_config_create, name='punchout_config_create'),
    path('punchout/<int:pk>/edit/', views.punchout_config_edit, name='punchout_config_edit'),
    path('punchout/<int:pk>/delete/', views.punchout_config_delete, name='punchout_config_delete'),
    path('punchout/<int:pk>/start/', views.punchout_start, name='punchout_start'),
    path('punchout/sessions/', views.punchout_session_list, name='punchout_session_list'),
    path('punchout/sessions/<int:pk>/', views.punchout_session_detail, name='punchout_session_detail'),
    path('punchout/sessions/<int:pk>/redirect/', views.punchout_redirect, name='punchout_redirect'),
    path('punchout/sessions/<int:pk>/to-requisition/', views.punchout_to_requisition, name='punchout_to_requisition'),
    path('punchout/sessions/<int:pk>/to-items/', views.punchout_to_items, name='punchout_to_items'),
    # Inbound supplier cart POST (CSRF-exempt, token-authenticated).
    path('punchout/return/<str:token>/', views.punchout_return, name='punchout_return'),

    # Supplier uploads (buyer review side)
    path('uploads/', views.upload_list, name='upload_list'),
    path('uploads/<int:pk>/', views.upload_detail, name='upload_detail'),
    path('uploads/<int:pk>/process/', views.upload_process, name='upload_process'),
    path('uploads/<int:pk>/delete/', views.upload_delete, name='upload_delete'),

    # Item detail + CRUD
    path('items/<int:pk>/', views.item_detail, name='item_detail'),
    path('items/<int:pk>/edit/', views.item_edit, name='item_edit'),
    path('items/<int:pk>/delete/', views.item_delete, name='item_delete'),
    path('items/<int:pk>/analytics/', views.item_analytics, name='item_analytics'),

    # Item lifecycle (POST)
    path('items/<int:pk>/submit/', views.item_submit, name='item_submit'),
    path('items/<int:pk>/approve/', views.item_approve, name='item_approve'),
    path('items/<int:pk>/reject/', views.item_reject, name='item_reject'),
    path('items/<int:pk>/retire/', views.item_retire, name='item_retire'),
    path('items/<int:pk>/archive/', views.item_archive, name='item_archive'),

    # Price tiers
    path('items/<int:pk>/tiers/add/', views.tier_add, name='tier_add'),
    path('items/<int:pk>/tiers/<int:tier_pk>/edit/', views.tier_edit, name='tier_edit'),
    path('items/<int:pk>/tiers/<int:tier_pk>/delete/', views.tier_delete, name='tier_delete'),

    # Price-change requests
    path('items/<int:pk>/price-change/new/', views.price_change_create, name='price_change_create'),
    path('items/<int:pk>/price-change/<int:pc_pk>/', views.price_change_detail, name='price_change_detail'),
    path('items/<int:pk>/price-change/<int:pc_pk>/submit/', views.price_change_submit, name='price_change_submit'),
    path('items/<int:pk>/price-change/<int:pc_pk>/apply/', views.price_change_apply, name='price_change_apply'),
    path('items/<int:pk>/price-change/<int:pc_pk>/reject/', views.price_change_reject, name='price_change_reject'),
    path('items/<int:pk>/price-change/<int:pc_pk>/cancel/', views.price_change_cancel, name='price_change_cancel'),
]

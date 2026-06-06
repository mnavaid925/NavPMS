from django.urls import path

from . import views

app_name = 'inventory'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # 1. Stock levels
    path('stock/', views.stock_list, name='stock_list'),
    path('stock/new/', views.stock_item_create, name='stock_item_create'),
    path('stock/<int:pk>/', views.stock_item_detail, name='stock_item_detail'),
    path('stock/<int:pk>/edit/', views.stock_item_edit, name='stock_item_edit'),
    path('stock/<int:pk>/adjust/', views.stock_item_adjust, name='stock_item_adjust'),
    path('stock/<int:pk>/delete/', views.stock_item_delete, name='stock_item_delete'),

    # Stock movement ledger (read-only)
    path('movements/', views.movement_list, name='movement_list'),
    path('movements/<int:pk>/', views.movement_detail, name='movement_detail'),

    # 4. Warehouses & locations
    path('warehouses/', views.warehouse_list, name='warehouse_list'),
    path('warehouses/new/', views.warehouse_create, name='warehouse_create'),
    path('warehouses/<int:pk>/', views.warehouse_detail, name='warehouse_detail'),
    path('warehouses/<int:pk>/edit/', views.warehouse_edit, name='warehouse_edit'),
    path('warehouses/<int:pk>/delete/', views.warehouse_delete, name='warehouse_delete'),
    path('locations/new/', views.location_create, name='location_create'),
    path('locations/<int:pk>/edit/', views.location_edit, name='location_edit'),
    path('locations/<int:pk>/delete/', views.location_delete, name='location_delete'),

    # 3. Goods issues / returns
    path('issues/', views.goods_issue_list, name='goods_issue_list'),
    path('issues/new/', views.goods_issue_create, name='goods_issue_create'),
    path('issues/<int:pk>/', views.goods_issue_detail, name='goods_issue_detail'),
    path('issues/<int:pk>/edit/', views.goods_issue_edit, name='goods_issue_edit'),
    path('issues/<int:pk>/lines/add/', views.goods_issue_line_add, name='goods_issue_line_add'),
    path('issues/<int:pk>/lines/<int:lpk>/delete/', views.goods_issue_line_delete,
         name='goods_issue_line_delete'),
    path('issues/<int:pk>/post/', views.goods_issue_post, name='goods_issue_post'),
    path('issues/<int:pk>/cancel/', views.goods_issue_cancel, name='goods_issue_cancel'),
    path('issues/<int:pk>/delete/', views.goods_issue_delete, name='goods_issue_delete'),

    # 5. Cycle counts
    path('cycle-counts/', views.cycle_count_list, name='cycle_count_list'),
    path('cycle-counts/new/', views.cycle_count_create, name='cycle_count_create'),
    path('cycle-counts/<int:pk>/', views.cycle_count_detail, name='cycle_count_detail'),
    path('cycle-counts/<int:pk>/edit/', views.cycle_count_edit, name='cycle_count_edit'),
    path('cycle-counts/<int:pk>/count/', views.cycle_count_count, name='cycle_count_count'),
    path('cycle-counts/<int:pk>/post/', views.cycle_count_post, name='cycle_count_post'),
    path('cycle-counts/<int:pk>/cancel/', views.cycle_count_cancel, name='cycle_count_cancel'),
    path('cycle-counts/<int:pk>/delete/', views.cycle_count_delete, name='cycle_count_delete'),

    # 2. Reorder automation
    path('reorder/', views.reorder_board, name='reorder_board'),
    path('reorder/run/', views.reorder_run, name='reorder_run'),
]

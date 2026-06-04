from django.urls import path

from . import views

app_name = 'goods_receipt'

urlpatterns = [
    # Dashboard / analytics
    path('', views.analytics_dashboard, name='dashboard'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),

    # List + create
    path('list/', views.grn_list, name='grn_list'),
    path('new/', views.grn_create, name='grn_create'),

    # Detail + CRUD
    path('<int:pk>/', views.grn_detail, name='grn_detail'),
    path('<int:pk>/edit/', views.grn_edit, name='grn_edit'),
    path('<int:pk>/delete/', views.grn_delete, name='grn_delete'),

    # Lifecycle (POST)
    path('<int:pk>/receive/', views.grn_receive, name='grn_receive'),
    path('<int:pk>/inspect/', views.grn_inspect, name='grn_inspect'),
    path('<int:pk>/post/', views.grn_post, name='grn_post'),
    path('<int:pk>/close/', views.grn_close, name='grn_close'),
    path('<int:pk>/cancel/', views.grn_cancel, name='grn_cancel'),

    # GRN lines
    path('<int:pk>/lines/add/', views.line_add, name='line_add'),
    path('<int:pk>/lines/<int:line_pk>/edit/', views.line_edit, name='line_edit'),
    path('<int:pk>/lines/<int:line_pk>/delete/', views.line_delete, name='line_delete'),

    # Tags (barcode / QR labels)
    path('<int:pk>/tags/', views.tags_print, name='tags_print'),
    path('<int:pk>/tags/generate/', views.grn_generate_tags, name='grn_generate_tags'),

    # Return to Vendor
    path('<int:pk>/rtv/new/', views.rtv_create, name='rtv_create'),
    path('rtv/<int:pk>/', views.rtv_detail, name='rtv_detail'),
    path('rtv/<int:pk>/lines/add/', views.rtv_line_add, name='rtv_line_add'),
    path('rtv/<int:pk>/lines/<int:line_pk>/delete/', views.rtv_line_delete,
         name='rtv_line_delete'),
    path('rtv/<int:pk>/authorize/', views.rtv_authorize, name='rtv_authorize'),
    path('rtv/<int:pk>/ship/', views.rtv_ship, name='rtv_ship'),
    path('rtv/<int:pk>/close/', views.rtv_close, name='rtv_close'),
    path('rtv/<int:pk>/cancel/', views.rtv_cancel, name='rtv_cancel'),
]

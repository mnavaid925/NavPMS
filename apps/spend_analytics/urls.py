from django.urls import path

from . import views

app_name = 'spend_analytics'

urlpatterns = [
    # Spend Dashboards
    path('', views.dashboard, name='dashboard'),
    path('analytics/', views.dashboard, name='analytics_dashboard'),  # sidebar parity alias

    # Category Spend Analysis
    path('categories/', views.category_analysis, name='category_analysis'),
    path('categories/<int:category_id>/', views.category_detail, name='category_detail'),

    # Maverick Spend Tracking
    path('maverick/', views.maverick_tracking, name='maverick_tracking'),

    # Custom Report Builder (full CRUD + run)
    path('reports/', views.report_list, name='report_list'),
    path('reports/new/', views.report_create, name='report_create'),
    path('reports/<int:pk>/', views.report_detail, name='report_detail'),  # run
    path('reports/<int:pk>/edit/', views.report_edit, name='report_edit'),
    path('reports/<int:pk>/delete/', views.report_delete, name='report_delete'),
    path('reports/<int:pk>/export.<str:fmt>', views.export_report, name='export_report'),

    # Manual fact-table refresh
    path('sync/', views.sync_now, name='sync_now'),

    # Data Export (the BI feed)
    path('export/dashboard.<str:fmt>', views.export_dashboard, name='export_dashboard'),
    path('export/records.<str:fmt>', views.export_records, name='export_records'),
]

from django.urls import path

from . import views

app_name = 'supplier_performance'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # KPI Definitions
    path('kpis/', views.kpi_list, name='kpi_list'),
    path('kpis/new/', views.kpi_create, name='kpi_create'),
    path('kpis/<int:pk>/edit/', views.kpi_edit, name='kpi_edit'),
    path('kpis/<int:pk>/delete/', views.kpi_delete, name='kpi_delete'),
    path('kpis/restore-defaults/', views.kpi_restore_defaults, name='kpi_restore_defaults'),

    # Scorecards
    path('scorecards/', views.scorecard_list, name='scorecard_list'),
    path('scorecards/generate/', views.scorecard_generate, name='scorecard_generate'),
    path('scorecards/<int:pk>/', views.scorecard_detail, name='scorecard_detail'),
    path('scorecards/<int:pk>/finalize/', views.scorecard_finalize, name='scorecard_finalize'),
    path('scorecards/<int:pk>/regenerate/', views.scorecard_regenerate, name='scorecard_regenerate'),
    path('scorecards/<int:pk>/delete/', views.scorecard_delete, name='scorecard_delete'),
    path('scorecards/<int:pk>/export.<str:fmt>', views.export_scorecard, name='export_scorecard'),

    # 360° Feedback
    path('feedback/', views.feedback_list, name='feedback_list'),
    path('feedback/request/', views.feedback_request, name='feedback_request'),
    path('feedback/<int:pk>/submit/', views.feedback_submit, name='feedback_submit'),
    path('feedback/<int:pk>/cancel/', views.feedback_cancel, name='feedback_cancel'),

    # Performance Improvement Plans
    path('pips/', views.pip_list, name='pip_list'),
    path('pips/new/', views.pip_create, name='pip_create'),
    path('pips/<int:pk>/', views.pip_detail, name='pip_detail'),
    path('pips/<int:pk>/edit/', views.pip_edit, name='pip_edit'),
    path('pips/<int:pk>/status/', views.pip_set_status, name='pip_set_status'),
    path('pips/<int:pk>/delete/', views.pip_delete, name='pip_delete'),
    path('pips/<int:pk>/actions/add/', views.pip_action_create, name='pip_action_create'),
    path('pips/<int:pk>/actions/<int:apk>/edit/', views.pip_action_edit, name='pip_action_edit'),
    path('pips/<int:pk>/actions/<int:apk>/delete/', views.pip_action_delete,
         name='pip_action_delete'),

    # Trending & Benchmarking
    path('trending/', views.trending, name='trending'),
    path('benchmarking/', views.benchmarking, name='benchmarking'),
    path('benchmarking/export.<str:fmt>', views.export_benchmark, name='export_benchmark'),
    path('vendors/<int:vendor_pk>/scorecards/', views.vendor_scorecards, name='vendor_scorecards'),
]

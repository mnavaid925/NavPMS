from django.urls import path

from . import views

app_name = 'budget'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Budget Periods (CRUD + lifecycle)
    path('periods/', views.period_list, name='period_list'),
    path('periods/new/', views.period_create, name='period_create'),
    path('periods/<int:pk>/', views.period_detail, name='period_detail'),
    path('periods/<int:pk>/edit/', views.period_edit, name='period_edit'),
    path('periods/<int:pk>/delete/', views.period_delete, name='period_delete'),
    path('periods/<int:pk>/status/', views.period_set_status, name='period_set_status'),

    # Budgets (CRUD + lifecycle)
    path('budgets/', views.budget_list, name='budget_list'),
    path('budgets/new/', views.budget_create, name='budget_create'),
    path('budgets/<int:pk>/', views.budget_detail, name='budget_detail'),
    path('budgets/<int:pk>/edit/', views.budget_edit, name='budget_edit'),
    path('budgets/<int:pk>/delete/', views.budget_delete, name='budget_delete'),
    path('budgets/<int:pk>/activate/', views.budget_activate, name='budget_activate'),
    path('budgets/<int:pk>/close/', views.budget_close, name='budget_close'),
    path('budgets/<int:pk>/forecast/', views.budget_forecast, name='budget_forecast'),
    path('budgets/<int:pk>/export.<str:fmt>', views.export_budget, name='export_budget'),

    # Allocation lines (inline on budget detail)
    path('budgets/<int:pk>/allocations/add/', views.allocation_create, name='allocation_create'),
    path('budgets/<int:pk>/allocations/<int:apk>/edit/', views.allocation_edit,
         name='allocation_edit'),
    path('budgets/<int:pk>/allocations/<int:apk>/delete/', views.allocation_delete,
         name='allocation_delete'),

    # Variance Analysis + export
    path('variance/', views.variance, name='variance'),
    path('variance/export.<str:fmt>', views.export_variance, name='export_variance'),

    # Availability-check audit log
    path('checks/', views.check_log, name='check_log'),
]

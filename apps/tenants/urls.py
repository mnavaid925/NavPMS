from django.urls import path
from . import views

app_name = 'tenants'

urlpatterns = [
    # Onboarding wizard
    path('onboarding/', views.OnboardingStartView.as_view(), name='onboarding_start'),
    path('onboarding/company/', views.OnboardingCompanyView.as_view(), name='onboarding_company'),
    path('onboarding/plan/', views.OnboardingPlanView.as_view(), name='onboarding_plan'),
    path('onboarding/complete/', views.OnboardingCompleteView.as_view(), name='onboarding_complete'),

    # Plans (super-admin CRUD + public pricing)
    path('plans/', views.PlanListView.as_view(), name='plan_list'),
    path('plans/create/', views.PlanCreateView.as_view(), name='plan_create'),
    path('plans/<int:pk>/', views.PlanDetailView.as_view(), name='plan_detail'),
    path('plans/<int:pk>/edit/', views.PlanEditView.as_view(), name='plan_edit'),
    path('plans/<int:pk>/delete/', views.PlanDeleteView.as_view(), name='plan_delete'),

    # Subscriptions
    path('subscriptions/', views.SubscriptionListView.as_view(), name='subscription_list'),
    path('subscriptions/<int:pk>/', views.SubscriptionDetailView.as_view(), name='subscription_detail'),
    path('subscriptions/change-plan/', views.SubscriptionAssignView.as_view(), name='subscription_assign'),
    path('subscriptions/<int:pk>/cancel/', views.SubscriptionCancelView.as_view(), name='subscription_cancel'),

    # Invoices
    path('invoices/', views.InvoiceListView.as_view(), name='invoice_list'),
    path('invoices/<int:pk>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<int:pk>/pay/', views.InvoicePayView.as_view(), name='invoice_pay'),

    # Branding
    path('branding/', views.BrandingEditView.as_view(), name='branding_edit'),

    # Security
    path('security/', views.SecurityEditView.as_view(), name='security_edit'),

    # Monitoring
    path('monitoring/', views.MonitoringDashboardView.as_view(), name='monitoring_dashboard'),
    path('monitoring/audit-logs/', views.AuditLogListView.as_view(), name='audit_log_list'),
]

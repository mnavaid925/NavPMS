from django.urls import path

from . import views

app_name = 'compliance'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # 1. Restricted-party screening
    path('screenings/', views.screening_list, name='screening_list'),
    path('screenings/run/', views.screening_run, name='screening_run'),
    path('screenings/<int:pk>/', views.screening_detail, name='screening_detail'),
    path('screenings/<int:pk>/matches/<int:mpk>/disposition/', views.screening_disposition,
         name='screening_disposition'),

    # Restricted-party reference list
    path('restricted-parties/', views.rpe_list, name='rpe_list'),
    path('restricted-parties/new/', views.rpe_create, name='rpe_create'),
    path('restricted-parties/<int:pk>/edit/', views.rpe_edit, name='rpe_edit'),
    path('restricted-parties/<int:pk>/delete/', views.rpe_delete, name='rpe_delete'),

    # 2. Financial-risk monitoring
    path('financial/', views.financial_list, name='financial_list'),
    path('financial/monitor/', views.financial_monitor, name='financial_monitor'),
    path('financial/<int:pk>/', views.financial_detail, name='financial_detail'),
    path('financial/<int:pk>/refresh/', views.financial_refresh, name='financial_refresh'),
    path('financial/<int:pk>/toggle/', views.financial_toggle, name='financial_toggle'),

    # 3. Audit trail explorer (tamper-evident)
    path('audit/', views.audit_log, name='audit_log'),
    path('audit/verify/', views.audit_verify, name='audit_verify'),
    path('audit/export.csv', views.audit_export, name='audit_export'),
    path('audit/<int:pk>/', views.audit_detail, name='audit_detail'),

    # 4. Fraud detection
    path('fraud/rules/', views.fraud_rule_list, name='fraud_rule_list'),
    path('fraud/rules/new/', views.fraud_rule_create, name='fraud_rule_create'),
    path('fraud/rules/<int:pk>/edit/', views.fraud_rule_edit, name='fraud_rule_edit'),
    path('fraud/rules/<int:pk>/delete/', views.fraud_rule_delete, name='fraud_rule_delete'),
    path('fraud/scan/', views.fraud_scan, name='fraud_scan'),
    path('fraud/alerts/', views.fraud_alert_list, name='fraud_alert_list'),
    path('fraud/alerts/<int:pk>/', views.fraud_alert_detail, name='fraud_alert_detail'),
    path('fraud/alerts/<int:pk>/status/', views.fraud_alert_status, name='fraud_alert_status'),
    path('fraud/alerts/<int:pk>/assign/', views.fraud_alert_assign, name='fraud_alert_assign'),

    # 5. Policy management & acknowledgment
    path('policies/', views.policy_list, name='policy_list'),
    path('policies/new/', views.policy_create, name='policy_create'),
    path('policies/<int:pk>/', views.policy_detail, name='policy_detail'),
    path('policies/<int:pk>/edit/', views.policy_edit, name='policy_edit'),
    path('policies/<int:pk>/delete/', views.policy_delete, name='policy_delete'),
    path('policies/<int:pk>/status/', views.policy_set_status, name='policy_set_status'),
    path('policies/<int:pk>/versions/new/', views.policy_version_create,
         name='policy_version_create'),
    path('policies/<int:pk>/versions/<int:vpk>/publish/', views.policy_publish,
         name='policy_publish'),
    path('my-policies/', views.my_policies, name='my_policies'),
    path('my-policies/<int:pk>/acknowledge/', views.policy_acknowledge, name='policy_acknowledge'),
]

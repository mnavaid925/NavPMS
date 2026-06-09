from django.urls import path

from . import views

app_name = 'sysadmin'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # 1. Roles & Permissions
    path('roles/', views.role_list, name='role_list'),
    path('roles/new/', views.role_create, name='role_create'),
    path('roles/<int:pk>/', views.role_detail, name='role_detail'),
    path('roles/<int:pk>/edit/', views.role_edit, name='role_edit'),
    path('roles/<int:pk>/permissions/', views.role_permissions, name='role_permissions'),
    path('roles/<int:pk>/delete/', views.role_delete, name='role_delete'),

    # 2. LDAP / SSO
    path('sso/', views.provider_list, name='provider_list'),
    path('sso/new/', views.provider_create, name='provider_create'),
    path('sso/<int:pk>/', views.provider_detail, name='provider_detail'),
    path('sso/<int:pk>/edit/', views.provider_edit, name='provider_edit'),
    path('sso/<int:pk>/test/', views.provider_test, name='provider_test'),
    path('sso/<int:pk>/simulate/', views.provider_simulate, name='provider_simulate'),
    path('sso/<int:pk>/delete/', views.provider_delete, name='provider_delete'),

    # 3. System Configuration & Setup
    path('config/', views.config_overview, name='config_overview'),
    path('config/currencies/', views.currency_list, name='currency_list'),
    path('config/currencies/new/', views.currency_create, name='currency_create'),
    path('config/currencies/<int:pk>/edit/', views.currency_edit, name='currency_edit'),
    path('config/currencies/<int:pk>/delete/', views.currency_delete, name='currency_delete'),
    path('config/tax-codes/', views.taxcode_list, name='taxcode_list'),
    path('config/tax-codes/new/', views.taxcode_create, name='taxcode_create'),
    path('config/tax-codes/<int:pk>/edit/', views.taxcode_edit, name='taxcode_edit'),
    path('config/tax-codes/<int:pk>/delete/', views.taxcode_delete, name='taxcode_delete'),
    path('config/sequences/', views.sequence_list, name='sequence_list'),
    path('config/sequences/new/', views.sequence_create, name='sequence_create'),
    path('config/sequences/<int:pk>/edit/', views.sequence_edit, name='sequence_edit'),
    path('config/sequences/<int:pk>/delete/', views.sequence_delete, name='sequence_delete'),

    # 4. Data Backup & Recovery
    path('backups/', views.backup_policy_list, name='backup_policy_list'),
    path('backups/new/', views.backup_policy_create, name='backup_policy_create'),
    path('backups/runs/', views.backup_run_list, name='backup_run_list'),
    path('backups/runs/export.csv', views.backup_run_export, name='backup_run_export'),
    path('backups/runs/<int:pk>/', views.backup_run_detail, name='backup_run_detail'),
    path('backups/runs/<int:pk>/restore/', views.restore_request, name='restore_request'),
    path('backups/restores/', views.restore_list, name='restore_list'),
    path('backups/restores/<int:pk>/decide/', views.restore_decide, name='restore_decide'),
    path('backups/<int:pk>/', views.backup_policy_detail, name='backup_policy_detail'),
    path('backups/<int:pk>/edit/', views.backup_policy_edit, name='backup_policy_edit'),
    path('backups/<int:pk>/run/', views.backup_run_now, name='backup_run_now'),
    path('backups/<int:pk>/delete/', views.backup_policy_delete, name='backup_policy_delete'),

    # 5. API & Webhook Management
    path('api/keys/', views.apikey_list, name='apikey_list'),
    path('api/keys/new/', views.apikey_create, name='apikey_create'),
    path('api/keys/<int:pk>/revoke/', views.apikey_revoke, name='apikey_revoke'),
    path('api/keys/<int:pk>/delete/', views.apikey_delete, name='apikey_delete'),
    path('api/webhooks/', views.webhook_list, name='webhook_list'),
    path('api/webhooks/new/', views.webhook_create, name='webhook_create'),
    path('api/webhooks/<int:pk>/', views.webhook_detail, name='webhook_detail'),
    path('api/webhooks/<int:pk>/edit/', views.webhook_edit, name='webhook_edit'),
    path('api/webhooks/<int:pk>/test/', views.webhook_test, name='webhook_test'),
    path('api/webhooks/<int:pk>/delete/', views.webhook_delete, name='webhook_delete'),
]

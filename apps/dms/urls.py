from django.urls import path

from . import views

app_name = 'dms'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # 1. Central document repository
    path('documents/', views.document_list, name='document_list'),
    path('documents/new/', views.document_create, name='document_create'),
    path('documents/<int:pk>/', views.document_detail, name='document_detail'),
    path('documents/<int:pk>/edit/', views.document_edit, name='document_edit'),
    path('documents/<int:pk>/delete/', views.document_delete, name='document_delete'),
    path('documents/<int:pk>/status/', views.document_set_status, name='document_set_status'),

    # 2. Versions (nested under a document)
    path('documents/<int:pk>/versions/new/', views.version_create, name='version_create'),
    path('documents/<int:pk>/versions/<int:vpk>/publish/', views.version_publish,
         name='version_publish'),
    path('documents/<int:pk>/versions/<int:vpk>/reindex/', views.version_reindex,
         name='version_reindex'),
    path('documents/<int:pk>/versions/<int:vpk>/download/', views.version_download,
         name='version_download'),

    # 3. Procurement policy library (category='policy')
    path('policies/', views.policy_library, name='policy_library'),

    # 5. Full-text search
    path('search/', views.search, name='search'),

    # 4. Best-practice template library
    path('templates/', views.policy_template_list, name='policy_template_list'),
    path('templates/new/', views.policy_template_create, name='policy_template_create'),
    path('templates/<int:pk>/', views.policy_template_detail, name='policy_template_detail'),
    path('templates/<int:pk>/edit/', views.policy_template_edit, name='policy_template_edit'),
    path('templates/<int:pk>/delete/', views.policy_template_delete, name='policy_template_delete'),
    path('templates/<int:pk>/clone/', views.policy_template_clone, name='policy_template_clone'),

    # CSV export
    path('export.csv', views.document_export, name='document_export'),
]

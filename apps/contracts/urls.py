from django.urls import path

from . import views

app_name = 'contracts'

urlpatterns = [
    # Dashboard / analytics
    path('', views.analytics_dashboard, name='dashboard'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),

    # Boards
    path('renewals/', views.renewals_board, name='renewals_board'),
    path('obligations/', views.obligation_board, name='obligation_board'),

    # Contract list + create
    path('list/', views.contract_list, name='contract_list'),
    path('new/', views.contract_create, name='contract_create'),

    # Clause library
    path('clauses/', views.clause_library_list, name='clause_list'),
    path('clauses/new/', views.clause_create, name='clause_create'),
    path('clauses/<int:pk>/edit/', views.clause_edit, name='clause_edit'),
    path('clauses/<int:pk>/delete/', views.clause_delete, name='clause_delete'),

    # Template library
    path('templates/', views.template_list, name='template_list'),
    path('templates/new/', views.template_create, name='template_create'),
    path('templates/<int:pk>/', views.template_detail, name='template_detail'),
    path('templates/<int:pk>/edit/', views.template_edit, name='template_edit'),
    path('templates/<int:pk>/delete/', views.template_delete, name='template_delete'),
    path('templates/<int:pk>/clauses/add/', views.template_clause_add, name='template_clause_add'),
    path('templates/<int:pk>/clauses/<int:clause_pk>/delete/',
         views.template_clause_delete, name='template_clause_delete'),
    path('templates/<int:pk>/use/', views.template_use, name='template_use'),

    # Contract detail + CRUD
    path('<int:pk>/', views.contract_detail, name='contract_detail'),
    path('<int:pk>/edit/', views.contract_edit, name='contract_edit'),
    path('<int:pk>/delete/', views.contract_delete, name='contract_delete'),
    path('<int:pk>/author/', views.contract_author, name='contract_author'),
    path('<int:pk>/save-as-template/', views.contract_save_as_template, name='contract_save_as_template'),

    # Authoring — clause lines
    path('<int:pk>/clauses/add/', views.clause_line_add, name='clause_line_add'),
    path('<int:pk>/clauses/add-from-library/',
         views.clause_line_add_from_library, name='clause_line_add_from_library'),
    path('<int:pk>/clauses/<int:line_pk>/edit/', views.clause_line_edit, name='clause_line_edit'),
    path('<int:pk>/clauses/<int:line_pk>/delete/', views.clause_line_delete, name='clause_line_delete'),

    # Lifecycle (POST)
    path('<int:pk>/send/', views.contract_send_for_signature, name='contract_send_for_signature'),
    path('<int:pk>/activate/', views.contract_activate, name='contract_activate'),
    path('<int:pk>/terminate/', views.contract_terminate, name='contract_terminate'),
    path('<int:pk>/cancel/', views.contract_cancel, name='contract_cancel'),
    path('<int:pk>/renew/', views.contract_renew, name='contract_renew'),

    # Signatories
    path('<int:pk>/signatories/add/', views.signatory_add, name='signatory_add'),
    path('<int:pk>/signatories/<int:signatory_pk>/remove/',
         views.signatory_remove, name='signatory_remove'),
    path('<int:pk>/signatories/<int:signatory_pk>/sign/',
         views.signatory_sign, name='signatory_sign'),

    # Amendments
    path('<int:pk>/amendments/new/', views.amendment_create, name='amendment_create'),
    path('<int:pk>/amendments/<int:amendment_pk>/', views.amendment_detail, name='amendment_detail'),
    path('<int:pk>/amendments/<int:amendment_pk>/apply/', views.amendment_apply, name='amendment_apply'),
    path('<int:pk>/amendments/<int:amendment_pk>/cancel/', views.amendment_cancel, name='amendment_cancel'),

    # Obligations
    path('<int:pk>/obligations/add/', views.obligation_add, name='obligation_add'),
    path('<int:pk>/obligations/<int:obligation_pk>/edit/', views.obligation_edit, name='obligation_edit'),
    path('<int:pk>/obligations/<int:obligation_pk>/delete/', views.obligation_delete, name='obligation_delete'),
    path('<int:pk>/obligations/<int:obligation_pk>/complete/', views.obligation_complete, name='obligation_complete'),
    path('<int:pk>/obligations/<int:obligation_pk>/waive/', views.obligation_waive, name='obligation_waive'),

    # Documents
    path('<int:pk>/documents/add/', views.document_add, name='document_add'),
    path('<int:pk>/documents/<int:document_pk>/delete/', views.document_delete, name='document_delete'),

    # Per-contract analytics
    path('<int:pk>/analytics/', views.contract_analytics, name='contract_analytics'),
]

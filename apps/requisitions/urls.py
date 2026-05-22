from django.urls import path
from . import views

app_name = 'requisitions'

urlpatterns = [
    # Account codes (master data)
    path('account-codes/', views.AccountCodeListView.as_view(), name='account_code_list'),
    path('account-codes/create/', views.AccountCodeCreateView.as_view(), name='account_code_create'),
    path('account-codes/<int:pk>/edit/', views.AccountCodeEditView.as_view(), name='account_code_edit'),
    path('account-codes/<int:pk>/delete/', views.AccountCodeDeleteView.as_view(), name='account_code_delete'),

    # Requisition templates
    path('templates/', views.TemplateListView.as_view(), name='template_list'),
    path('templates/create/', views.TemplateCreateView.as_view(), name='template_create'),
    path('templates/<int:pk>/', views.TemplateDetailView.as_view(), name='template_detail'),
    path('templates/<int:pk>/edit/', views.TemplateEditView.as_view(), name='template_edit'),
    path('templates/<int:pk>/delete/', views.TemplateDeleteView.as_view(), name='template_delete'),
    path('templates/<int:pk>/use/', views.TemplateUseView.as_view(), name='template_use'),
    path('templates/<int:pk>/lines/add/', views.TemplateLineAddView.as_view(), name='template_line_add'),
    path('templates/<int:pk>/lines/<int:line_pk>/delete/', views.TemplateLineDeleteView.as_view(), name='template_line_delete'),

    # Requisition tracking board
    path('tracking/', views.RequisitionTrackingView.as_view(), name='tracking'),

    # Requisitions
    path('', views.RequisitionListView.as_view(), name='requisition_list'),
    path('create/', views.RequisitionCreateView.as_view(), name='requisition_create'),
    path('<int:pk>/', views.RequisitionDetailView.as_view(), name='requisition_detail'),
    path('<int:pk>/edit/', views.RequisitionEditView.as_view(), name='requisition_edit'),
    path('<int:pk>/delete/', views.RequisitionDeleteView.as_view(), name='requisition_delete'),
    path('<int:pk>/lines/add/', views.RequisitionLineAddView.as_view(), name='requisition_line_add'),
    path('<int:pk>/lines/<int:line_pk>/delete/', views.RequisitionLineDeleteView.as_view(), name='requisition_line_delete'),

    # Workflow actions
    path('<int:pk>/submit/', views.RequisitionSubmitView.as_view(), name='requisition_submit'),
    path('<int:pk>/decide/', views.RequisitionDecideView.as_view(), name='requisition_decide'),
    path('<int:pk>/cancel/', views.RequisitionCancelView.as_view(), name='requisition_cancel'),
    path('<int:pk>/amend/', views.RequisitionAmendView.as_view(), name='requisition_amend'),
    path('<int:pk>/convert/', views.RequisitionConvertView.as_view(), name='requisition_convert'),
]

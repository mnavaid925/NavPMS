from django.urls import path

from . import views

app_name = 'invoicing'

urlpatterns = [
    # Dashboard / analytics
    path('', views.analytics_dashboard, name='dashboard'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),

    # Invoices — list + create
    path('list/', views.invoice_list, name='invoice_list'),
    path('new/', views.invoice_create, name='invoice_create'),
    path('capture/', views.invoice_capture, name='invoice_capture'),

    # Invoice detail + CRUD
    path('<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('<int:pk>/edit/', views.invoice_edit, name='invoice_edit'),
    path('<int:pk>/delete/', views.invoice_delete, name='invoice_delete'),

    # Invoice lifecycle (POST)
    path('<int:pk>/submit/', views.invoice_submit, name='invoice_submit'),
    path('<int:pk>/match/', views.invoice_match, name='invoice_match'),
    path('<int:pk>/approve/', views.invoice_approve, name='invoice_approve'),
    path('<int:pk>/dispute/', views.invoice_dispute, name='invoice_dispute'),
    path('<int:pk>/dispute/note/', views.invoice_dispute_note, name='invoice_dispute_note'),
    path('<int:pk>/resolve/', views.invoice_resolve, name='invoice_resolve'),
    path('<int:pk>/reject/', views.invoice_reject, name='invoice_reject'),
    path('<int:pk>/cancel/', views.invoice_cancel, name='invoice_cancel'),

    # Invoice lines
    path('<int:pk>/lines/add/', views.line_add, name='line_add'),
    path('<int:pk>/lines/<int:line_pk>/edit/', views.line_edit, name='line_edit'),
    path('<int:pk>/lines/<int:line_pk>/delete/', views.line_delete, name='line_delete'),

    # Payment vouchers
    path('<int:pk>/voucher/new/', views.voucher_create, name='voucher_create'),
    path('vouchers/', views.voucher_list, name='voucher_list'),
    path('vouchers/<int:pk>/', views.voucher_detail, name='voucher_detail'),
    path('vouchers/<int:pk>/approve/', views.voucher_approve, name='voucher_approve'),
    path('vouchers/<int:pk>/schedule/', views.voucher_schedule, name='voucher_schedule'),
    path('vouchers/<int:pk>/pay/', views.voucher_pay, name='voucher_pay'),
    path('vouchers/<int:pk>/cancel/', views.voucher_cancel, name='voucher_cancel'),

    # Payment terms master
    path('terms/', views.term_list, name='term_list'),
    path('terms/new/', views.term_create, name='term_create'),
    path('terms/<int:pk>/edit/', views.term_edit, name='term_edit'),
    path('terms/<int:pk>/delete/', views.term_delete, name='term_delete'),
]

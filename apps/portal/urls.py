from django.urls import path
from . import views

app_name = 'portal'

urlpatterns = [
    # Personalized dashboard
    path('', views.PortalDashboardView.as_view(), name='dashboard'),

    # Widgets (dashboard customization)
    path('widgets/', views.WidgetListView.as_view(), name='widget_list'),
    path('widgets/create/', views.WidgetCreateView.as_view(), name='widget_create'),
    path('widgets/<int:pk>/edit/', views.WidgetEditView.as_view(), name='widget_edit'),
    path('widgets/<int:pk>/delete/', views.WidgetDeleteView.as_view(), name='widget_delete'),

    # Task & Alert Center
    path('notifications/', views.NotificationListView.as_view(), name='notification_list'),
    path('notifications/create/', views.NotificationCreateView.as_view(), name='notification_create'),
    path('notifications/mark-all-read/', views.NotificationMarkAllReadView.as_view(), name='notification_mark_all_read'),
    path('notifications/<int:pk>/', views.NotificationDetailView.as_view(), name='notification_detail'),
    path('notifications/<int:pk>/edit/', views.NotificationEditView.as_view(), name='notification_edit'),
    path('notifications/<int:pk>/delete/', views.NotificationDeleteView.as_view(), name='notification_delete'),
    path('notifications/<int:pk>/toggle-read/', views.NotificationMarkReadView.as_view(), name='notification_mark_read'),

    # Quick Requisition Entry
    path('requisitions/', views.RequisitionListView.as_view(), name='requisition_list'),
    path('requisitions/create/', views.RequisitionCreateView.as_view(), name='requisition_create'),
    path('requisitions/<int:pk>/', views.RequisitionDetailView.as_view(), name='requisition_detail'),
    path('requisitions/<int:pk>/edit/', views.RequisitionEditView.as_view(), name='requisition_edit'),
    path('requisitions/<int:pk>/delete/', views.RequisitionDeleteView.as_view(), name='requisition_delete'),
    path('requisitions/<int:pk>/submit/', views.RequisitionSubmitView.as_view(), name='requisition_submit'),
    path('requisitions/<int:pk>/items/add/', views.RequisitionItemAddView.as_view(), name='requisition_item_add'),
    path('requisitions/<int:pk>/items/<int:item_pk>/delete/', views.RequisitionItemDeleteView.as_view(), name='requisition_item_delete'),

    # Recent Activity Feed
    path('activity/', views.ActivityFeedView.as_view(), name='activity_feed'),

    # Self-Service Reporting
    path('reports/', views.ReportListView.as_view(), name='report_list'),
    path('reports/create/', views.ReportCreateView.as_view(), name='report_create'),
    path('reports/<int:pk>/', views.ReportRunView.as_view(), name='report_run'),
    path('reports/<int:pk>/edit/', views.ReportEditView.as_view(), name='report_edit'),
    path('reports/<int:pk>/delete/', views.ReportDeleteView.as_view(), name='report_delete'),
]

from django.urls import path
from . import views

app_name = 'approvals'

urlpatterns = [
    # Approver inbox (mobile-friendly) + tasks
    path('', views.InboxView.as_view(), name='inbox'),
    path('tasks/<int:pk>/', views.TaskDetailView.as_view(), name='task_detail'),
    path('tasks/<int:pk>/act/', views.TaskActView.as_view(), name='task_act'),
    path('tasks/<int:pk>/comment/', views.TaskCommentView.as_view(), name='task_comment'),

    # Approval rules
    path('rules/', views.RuleListView.as_view(), name='rule_list'),
    path('rules/create/', views.RuleCreateView.as_view(), name='rule_create'),
    path('rules/<int:pk>/', views.RuleDetailView.as_view(), name='rule_detail'),
    path('rules/<int:pk>/edit/', views.RuleEditView.as_view(), name='rule_edit'),
    path('rules/<int:pk>/delete/', views.RuleDeleteView.as_view(), name='rule_delete'),
    path('rules/<int:pk>/steps/add/', views.StepAddView.as_view(), name='step_add'),
    path('rules/<int:pk>/steps/<int:step_pk>/delete/', views.StepDeleteView.as_view(), name='step_delete'),

    # Delegations
    path('delegations/', views.DelegationListView.as_view(), name='delegation_list'),
    path('delegations/create/', views.DelegationCreateView.as_view(), name='delegation_create'),
    path('delegations/<int:pk>/edit/', views.DelegationEditView.as_view(), name='delegation_edit'),
    path('delegations/<int:pk>/delete/', views.DelegationDeleteView.as_view(), name='delegation_delete'),

    # Approval requests
    path('requests/', views.RequestListView.as_view(), name='request_list'),
    path('requests/<int:pk>/', views.RequestDetailView.as_view(), name='request_detail'),

    # History
    path('history/', views.HistoryView.as_view(), name='history'),
]

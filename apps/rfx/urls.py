"""Internal (buyer-side) URLs for Module 7 — RFx Management."""
from django.urls import path

from . import views

app_name = 'rfx'

urlpatterns = [
    # Events
    path('events/', views.event_list, name='event_list'),
    path('events/new/', views.event_create, name='event_create'),
    path('events/<int:pk>/', views.event_detail, name='event_detail'),
    path('events/<int:pk>/edit/', views.event_edit, name='event_edit'),
    path('events/<int:pk>/delete/', views.event_delete, name='event_delete'),

    # Event lifecycle
    path('events/<int:pk>/publish/', views.event_publish, name='event_publish'),
    path('events/<int:pk>/open/', views.event_open, name='event_open'),
    path('events/<int:pk>/close/', views.event_close, name='event_close'),
    path('events/<int:pk>/cancel/', views.event_cancel, name='event_cancel'),
    path('events/<int:pk>/complete/', views.event_complete, name='event_complete'),
    path('events/<int:pk>/save-template/',
         views.event_save_as_template, name='event_save_as_template'),

    # Sections (inline on event detail)
    path('events/<int:pk>/sections/add/', views.section_create, name='section_create'),
    path('events/<int:pk>/sections/<int:spk>/edit/',
         views.section_edit, name='section_edit'),
    path('events/<int:pk>/sections/<int:spk>/delete/',
         views.section_delete, name='section_delete'),
    path('events/<int:pk>/sections/<int:spk>/move/<str:direction>/',
         views.section_move, name='section_move'),

    # Questions (inline on event detail, scoped to section)
    path('events/<int:pk>/sections/<int:spk>/questions/add/',
         views.question_create, name='question_create'),
    path('events/<int:pk>/questions/<int:qpk>/edit/',
         views.question_edit, name='question_edit'),
    path('events/<int:pk>/questions/<int:qpk>/delete/',
         views.question_delete, name='question_delete'),
    path('events/<int:pk>/questions/<int:qpk>/move/<str:direction>/',
         views.question_move, name='question_move'),

    # Invitees
    path('events/<int:pk>/invitees/add/', views.invitee_add, name='invitee_add'),
    path('events/<int:pk>/invitees/<int:ipk>/remove/',
         views.invitee_remove, name='invitee_remove'),

    # Documents (buyer-side attachments)
    path('events/<int:pk>/documents/add/', views.document_add, name='document_add'),
    path('events/<int:pk>/documents/<int:dpk>/delete/',
         views.document_delete, name='document_delete'),

    # Responses (sealed list / detail / compare / evaluate / decisions)
    path('events/<int:pk>/responses/', views.response_list, name='response_list'),
    path('events/<int:pk>/responses/compare/',
         views.response_compare, name='response_compare'),
    path('events/<int:pk>/responses/<int:rpk>/',
         views.response_detail, name='response_detail'),
    path('events/<int:pk>/responses/<int:rpk>/evaluate/',
         views.response_evaluate, name='response_evaluate'),
    path('events/<int:pk>/responses/<int:rpk>/shortlist/',
         views.response_shortlist, name='response_shortlist'),
    path('events/<int:pk>/responses/<int:rpk>/reject/',
         views.response_reject, name='response_reject'),

    # Templates (library)
    path('templates/', views.template_list, name='template_list'),
    path('templates/new/', views.template_create, name='template_create'),
    path('templates/<int:pk>/', views.template_detail, name='template_detail'),
    path('templates/<int:pk>/edit/', views.template_edit, name='template_edit'),
    path('templates/<int:pk>/delete/', views.template_delete, name='template_delete'),
    path('templates/<int:pk>/use/', views.template_use, name='template_use'),

    # Template sections + questions (inline on template detail)
    path('templates/<int:pk>/sections/add/',
         views.template_section_create, name='template_section_create'),
    path('templates/<int:pk>/sections/<int:spk>/edit/',
         views.template_section_edit, name='template_section_edit'),
    path('templates/<int:pk>/sections/<int:spk>/delete/',
         views.template_section_delete, name='template_section_delete'),
    path('templates/<int:pk>/sections/<int:spk>/questions/add/',
         views.template_question_create, name='template_question_create'),
    path('templates/<int:pk>/questions/<int:qpk>/edit/',
         views.template_question_edit, name='template_question_edit'),
    path('templates/<int:pk>/questions/<int:qpk>/delete/',
         views.template_question_delete, name='template_question_delete'),

    # Analytics
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),
    path('events/<int:pk>/analytics/',
         views.analytics_event_report, name='analytics_event_report'),
]

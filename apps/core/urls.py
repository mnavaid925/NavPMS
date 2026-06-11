"""Core app URLs are mounted at root via config/urls.py (DashboardView + search)."""
from django.urls import path

from apps.core.views import GlobalSearchView

app_name = 'core'

urlpatterns = [
    path('search/', GlobalSearchView.as_view(), name='search'),
]

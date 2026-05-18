from django.contrib import admin
from apps.core.models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'industry', 'is_active', 'created_at')
    list_filter = ('is_active', 'industry')
    search_fields = ('name', 'slug', 'email', 'domain')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at', 'updated_at')

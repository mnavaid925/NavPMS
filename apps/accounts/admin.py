from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User, UserProfile, UserInvite


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        'username', 'email', 'first_name', 'last_name',
        'tenant', 'role', 'is_tenant_admin', 'is_active',
    )
    list_filter = ('role', 'is_tenant_admin', 'is_active', 'tenant')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('Tenant & Role', {
            'fields': ('tenant', 'role', 'is_tenant_admin',
                       'avatar', 'phone', 'job_title'),
        }),
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'theme', 'layout', 'sidebar_color', 'direction')
    list_filter = ('theme', 'layout', 'sidebar_color', 'direction')
    search_fields = ('user__username', 'user__email')


@admin.register(UserInvite)
class UserInviteAdmin(admin.ModelAdmin):
    list_display = ('email', 'tenant', 'role', 'status', 'invited_by', 'expires_at')
    list_filter = ('status', 'role', 'tenant')
    search_fields = ('email',)
    readonly_fields = ('token', 'created_at', 'updated_at', 'accepted_at')

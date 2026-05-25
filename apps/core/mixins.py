"""Permission mixins: tenant + role gating for class-based views."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect


class TenantRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """User must be authenticated AND belong to a tenant."""

    def test_func(self):
        return getattr(self.request, 'tenant', None) is not None

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return redirect('tenants:onboarding_start')
        return super().handle_no_permission()


class TenantAdminRequiredMixin(TenantRequiredMixin):
    """Tenant admin (or super-admin) only."""

    def test_func(self):
        if not super().test_func():
            return False
        u = self.request.user
        return getattr(u, 'is_tenant_admin', False) or u.is_superuser

    def handle_no_permission(self):
        user = self.request.user
        has_tenant = getattr(self.request, 'tenant', None) is not None
        if user.is_authenticated and has_tenant:
            messages.error(
                self.request,
                'Tenant admin permission required to access that page.',
            )
            return redirect('portal:dashboard')
        return super().handle_no_permission()


class SuperAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Platform super-admin only (cross-tenant operations)."""

    def test_func(self):
        u = self.request.user
        return u.is_superuser or getattr(u, 'role', '') == 'super_admin'

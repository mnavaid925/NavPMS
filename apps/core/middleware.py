"""TenantMiddleware: populates request.tenant from the authenticated user."""
from apps.core.models import set_current_tenant


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = None
        if request.user.is_authenticated and hasattr(request.user, 'tenant'):
            tenant = request.user.tenant
        request.tenant = tenant
        set_current_tenant(tenant)
        try:
            response = self.get_response(request)
        finally:
            set_current_tenant(None)
        return response

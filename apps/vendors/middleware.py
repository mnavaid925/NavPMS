"""VendorPortalSandboxMiddleware: keeps vendor portal users inside /vendor-portal/.

If an authenticated user has `user.vendor` set, they are restricted to the vendor
portal namespace, plus auth endpoints and the Django admin (so a superuser flag
can still rescue the account). Everything else redirects to /vendor-portal/.
"""
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


ALLOWED_PREFIXES = (
    '/vendor-portal/',
    '/accounts/',     # login / logout / password reset
    '/admin/',        # Django admin (gated separately)
    '/static/',
    '/media/',
)


class VendorPortalSandboxMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, 'is_vendor_user', False)
            and not request.path.startswith(ALLOWED_PREFIXES)
        ):
            messages.info(
                request, 'Vendor portal users are limited to /vendor-portal/.',
            )
            return redirect('vendor_portal:dashboard')
        return self.get_response(request)

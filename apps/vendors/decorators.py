"""View decorators for the Vendor Portal sandbox.

`vendor_required` -> only users with `user.vendor` set may pass (portal routes).
`vendor_blocked`  -> portal users are kicked back to /vendor-portal/ (internal routes).
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def vendor_required(view_func):
    """Allow only logged-in vendor-portal users."""

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not getattr(user, 'is_vendor_user', False):
            messages.error(
                request, 'This page is for vendor portal users only.',
            )
            return redirect('dashboard')
        vendor = user.vendor
        if vendor and vendor.status in ('blacklisted', 'inactive'):
            messages.error(
                request,
                'Your account is blocked. Please contact the buyer organisation.',
            )
            return redirect('accounts:logout')
        return view_func(request, *args, **kwargs)

    return _wrapped


def vendor_blocked(view_func):
    """Block vendor-portal users from internal/tenant-admin routes."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated and getattr(user, 'is_vendor_user', False):
            messages.info(
                request, 'Vendor portal users are limited to /vendor-portal/.',
            )
            return redirect('vendor_portal:dashboard')
        return view_func(request, *args, **kwargs)

    return _wrapped

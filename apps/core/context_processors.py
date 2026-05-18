"""Template context processors: tenant + branding + UI preferences."""
from django.conf import settings


def tenant_context(request):
    tenant = getattr(request, 'tenant', None)
    branding = None
    if tenant is not None:
        branding = getattr(tenant, 'branding', None)
    return {
        'current_tenant': tenant,
        'branding': branding,
        'app_name': getattr(settings, 'APP_NAME', 'NavPMS'),
    }


def ui_preferences(request):
    """Expose the logged-in user's theme/layout preferences to every template."""
    defaults = {
        'ui_theme': 'light',
        'ui_layout': 'vertical',
        'ui_sidebar_size': 'default',
        'ui_sidebar_color': 'light',
        'ui_topbar_color': 'light',
        'ui_layout_width': 'fluid',
        'ui_layout_position': 'fixed',
        'ui_direction': 'ltr',
    }
    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile is not None:
            defaults.update({
                'ui_theme': profile.theme,
                'ui_layout': profile.layout,
                'ui_sidebar_size': profile.sidebar_size,
                'ui_sidebar_color': profile.sidebar_color,
                'ui_topbar_color': profile.topbar_color,
                'ui_layout_width': profile.layout_width,
                'ui_layout_position': profile.layout_position,
                'ui_direction': profile.direction,
            })
    return defaults

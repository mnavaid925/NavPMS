"""Template helpers for RFx — dict access by variable key."""
from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Return mapping[key] if mapping is dict-like, else None.

    Used to look up per-question answers / scores by pk in a Django template
    without changing the view shape.
    """
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        try:
            return mapping[key]
        except (KeyError, TypeError, IndexError):
            return None

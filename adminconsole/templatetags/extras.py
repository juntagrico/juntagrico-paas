import re

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def juntagrico_version_badge(version_str):
    """Return a Bootstrap badge class for a juntagrico version string.
    Green for >= 2.0, yellow (warning) for ~1.7, red (danger) for older versions.
    Returns empty string if version cannot be parsed.
    """
    if not version_str:
        return ''
    match = re.match(r'(\d+)(?:\.(\d+))?', str(version_str))
    if not match:
        return ''
    major = int(match.group(1))
    minor = int(match.group(2)) if match.group(2) else 0
    if major >= 2:
        return 'bg-success text-white'
    elif major == 1 and minor >= 7:
        return 'bg-warning text-dark'
    else:
        return 'bg-danger text-white'


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def running_badge(running):
    """Return a colored circle span for a boolean running status."""
    if running:
        return mark_safe('<span class="status-circle status-circle-active"></span>')
    else:
        return mark_safe('<span class="status-circle status-circle-inactive"></span>')


@register.filter
def get_default_minute(form, cj_def):
    """Return the default minute for a cronjob, respecting 'spread' vs int."""
    return form.get_default_minute(cj_def)


@register.filter
def is_dict(value):
    """Return True if the value is a dictionary."""
    return isinstance(value, dict)


@register.filter
def is_sequence(value):
    """Return True if the value is a list or tuple (but not a string)."""
    return isinstance(value, (list, tuple))



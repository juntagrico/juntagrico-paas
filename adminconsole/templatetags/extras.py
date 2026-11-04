import re

from django import template
from django.utils.html import escape
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
def get_default_minute(form, cj_def):
    """Return the default minute for a cronjob, respecting 'spread' vs int."""
    return form.get_default_minute(cj_def)


@register.filter
def value_type_of(value):
    """Return the type name of a value for template branching."""
    if isinstance(value, dict):
        return 'dict'
    elif isinstance(value, (list, tuple)):
        return type(value).__name__
    else:
        return 'scalar'


@register.simple_tag(takes_context=True)
def render_value(context, value):
    """Recursively render a value as HTML, masking sensitive keys."""
    if value == '****':
        return mark_safe('<code class="text-muted">****</code>')
    elif isinstance(value, dict):
        pairs = []
        for k, v in value.items():
            cell = render_value(context, v)
            pairs.append(
                '<div class="row mb-1">'
                '<div class="col-auto" style="min-width: 120px;">'
                '<code class="text-dark">' + escape(str(k)) + '</code>'
                '</div>'
                '<div class="col">' + cell + '</div>'
                '</div>'
            )
        return mark_safe(
            '<div class="card card-body border-left bg-light" style="border-left-width: 3px; border-left-color: #6c757d; font-size: 0.9em; margin-left: 1rem; margin-bottom: 0.5rem;">'
            + ''.join(pairs) + '</div>'
        )
    elif isinstance(value, (list, tuple)):
        items = []
        for item in value:
            cell = render_value(context, item)
            items.append(f'<li>{cell}</li>')
        return mark_safe('<ul class="mb-0 pl-3" style="font-size: 0.9em;">' + ''.join(items) + '</ul>')
    else:
        return mark_safe(f'<code class="text-dark">{escape(str(value))}</code>')

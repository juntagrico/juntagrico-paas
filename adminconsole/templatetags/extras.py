from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


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
        return '<code class="text-muted">****</code>'
    elif isinstance(value, dict):
        pairs = []
        for k, v in value.items():
            cell = render_value(context, v)
            pairs.append(
                '<div class="mb-1">'
                '<span class="text-muted"><small>' + escape(str(k)) + '</small></span> '
                + cell + '</div>'
            )
        return mark_safe(
            '<div class="border-start border-2 border-secondary ps-2 ms-1" style="font-size: 0.9em;">'
            + ''.join(pairs) + '</div>'
        )
    elif isinstance(value, (list, tuple)):
        items = []
        for item in value:
            cell = render_value(context, item)
            items.append(f'<li>{cell}</li>')
        return mark_safe('<ul class="mb-0" style="font-size: 0.9em;">' + ''.join(items) + '</ul>')
    else:
        return mark_safe(f'<code>{escape(str(value))}</code>')

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


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


@register.filter
def dict_items(value):
    """Return dict.items() explicitly to avoid conflicts with a dict key named 'items'."""
    if isinstance(value, dict):
        return value.items()
    return []

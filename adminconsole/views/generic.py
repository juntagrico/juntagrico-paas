from functools import wraps

from django.shortcuts import render


def confirm_post(page_title, button_text):
    """
    Runs the view only on POST, so the action is protected against CSRF.
    Any other request shows a page to confirm the action, which then submits a POST.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method == 'POST':
                return view(request, *args, **kwargs)
            return render(request, 'generic/submit.html', {
                'page_title': page_title,
                'button_text': button_text,
            })

        return wrapper

    return decorator

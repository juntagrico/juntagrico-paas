import logging
from functools import wraps

from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render

security_log = logging.getLogger('adminconsole.security')

# wrong passwords in a row before the session is logged out
MAX_PASSWORD_FAILURES = 5


def client_address(request):
    # nginx passes the address of the client (proxy_params), gunicorn listens on a unix socket
    return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR') or '-'


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


def confirm_password(page_title, button_text):
    """
    Runs the view only on POST with the password of the user, e.g. before member data is exported,
    so a stolen session alone is not enough. After too many wrong passwords the session is logged out.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            error = ''
            if request.method == 'POST':
                if request.user.check_password(request.POST.get('password', '')):
                    request.session.pop('password_failures', None)
                    return view(request, *args, **kwargs)
                failures = request.session.get('password_failures', 0) + 1
                request.session['password_failures'] = failures
                security_log.warning('wrong password (%d) for %s by %s from %s',
                                     failures, request.path, request.user, client_address(request))
                if failures >= MAX_PASSWORD_FAILURES:
                    logout(request)
                    return redirect_to_login(request.get_full_path())
                error = 'Das Passwort ist falsch.'
            return render(request, 'generic/confirm_password.html', {
                'page_title': page_title,
                'button_text': button_text,
                'error': error,
            })

        return wrapper

    return decorator

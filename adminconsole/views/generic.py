import logging
from functools import wraps

from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import render, redirect

from adminconsole.forms import ProfileForm
from adminconsole.models import App
from adminconsole.util import pid_finished
from adminconsole.util.docker import get_container_statuses

audit_log = logging.getLogger('adminconsole.audit')

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
            return render(
                request,
                'generic/submit.html',
                {
                    'page_title': page_title,
                    'button_text': button_text,
                },
            )

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
                audit_log.warning(
                    'wrong password (%d) for %s by %s from %s',
                    failures,
                    request.path,
                    request.user,
                    client_address(request),
                )
                if failures >= MAX_PASSWORD_FAILURES:
                    logout(request)
                    return redirect_to_login(request.get_full_path())
                error = 'Das Passwort ist falsch.'
            return render(
                request,
                'generic/confirm_password.html',
                {
                    'page_title': page_title,
                    'button_text': button_text,
                    'error': error,
                },
            )

        return wrapper

    return decorator


@login_required
def home(request):
    superuser = request.user.is_superuser
    if superuser:
        available_apps = App.objects.filter(staging_of__isnull=True).order_by('name')
    else:
        available_apps = request.user.app.filter(staging_of__isnull=True).order_by(
            'name'
        )
    number_of_apps = available_apps.count()
    if number_of_apps == 1 and not superuser:
        return redirect('overview', app_id=available_apps[0].id)

    # Group apps by their first letter
    from collections import defaultdict

    grouped_apps = defaultdict(list)
    for app in available_apps:
        first_letter = app.name[0].upper() if app.name else '#'
        grouped_apps[first_letter].append(app)

    return render(
        request,
        'generic/home.html',
        {
            'grouped_apps': dict(sorted(grouped_apps.items())),
            'number_of_apps': number_of_apps,
            'can_add_app': number_of_apps < 1 or superuser,
        },
    )


@login_required
def profile(request):
    user = request.user
    if request.method == 'POST':
        form = ProfileForm(request.POST)
        if form.is_valid():
            user.email = form.cleaned_data.get('email')
            user.save()
            return redirect('/')
    else:
        form = ProfileForm({'email': user.email})
    return render(request, 'generic/profile.html', {'form': form})


@login_required
def pidcheck(request, pid):
    return JsonResponse({'finished': pid_finished(pid)})


@login_required
def health_status(request):
    """AJAX endpoint returning running and health status for all apps accessible to the user."""
    superuser = request.user.is_superuser
    if superuser:
        app_names = set(App.objects.values_list('name', flat=True))
    else:
        app_names = set(request.user.app.values_list('name', flat=True))
    app_versions = dict(
        App.objects.filter(name__in=app_names).values_list('name', 'version')
    )
    container_statuses = get_container_statuses(app_names, app_versions)

    # Build a flat dict: {app_name: {'running': bool, 'health': str|None}}
    result = {}
    for name, status in container_statuses.items():
        result[name] = {
            'running': status['running'],
            'health': status.get('health'),
        }
    return JsonResponse(result)

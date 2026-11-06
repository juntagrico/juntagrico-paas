from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from docker.errors import APIError, DockerException

from adminconsole.decorators import owner_of_app
from adminconsole.models import App
from adminconsole.util import generate_password
from adminconsole.util.admin import ADMIN_USERNAME, set_admin_password
from adminconsole.util.docker import create_container, stop_container
from adminconsole.views.generic import confirm_post


@require_POST
@owner_of_app
def start(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    if app.staging_of:
        app.renew()

    try:
        create_container(app)
    except (DockerException, APIError) as e:
        messages.error(request, str(e))
        return redirect('overview', app.id)

    return redirect('overview', app.id)


@require_POST
@owner_of_app
def stop(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    try:
        stop_container(app.name)
    except (DockerException, APIError) as e:
        messages.error(request, str(e))

    return redirect('overview', app.id)


@staff_member_required
@confirm_post('Admin-Passwort neu setzen', 'Neues Passwort setzen')
@never_cache
def reset_admin_password(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    password = generate_password()
    try:
        result = set_admin_password(app.container, password)
    except DockerException as e:
        messages.error(request, str(e))
        return redirect('overview', app.id)
    if result.exit_code != 0:
        messages.error(
            request,
            f'Das Passwort konnte nicht gesetzt werden. Gibt es den Benutzer «{ADMIN_USERNAME}»?',
        )
        return redirect('overview', app.id)

    # shown once and never stored, also not in messages, which may end up in a cookie
    return render(
        request,
        'app/admin_password.html',
        {'app': app, 'username': ADMIN_USERNAME, 'password': password},
    )

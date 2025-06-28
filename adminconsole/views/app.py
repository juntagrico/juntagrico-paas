from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from docker.errors import APIError

from adminconsole.decorators import owner_of_app
from adminconsole.models import App


@require_POST
@owner_of_app
def start(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    try:
        app.container.start()
    except APIError as e:
        messages.error(request, str(e))

    return redirect('overview', app.id)


@require_POST
@owner_of_app
def stop(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    try:
        app.container.stop()
    except APIError as e:
        messages.error(request, str(e))

    return redirect('overview', app.id)

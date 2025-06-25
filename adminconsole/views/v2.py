import subprocess

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from adminconsole.decorators import owner_of_app
from adminconsole.models import App


@owner_of_app
def redeploy(request, app_id, upgrade=False):
    app = get_object_or_404(App, pk=app_id)
    if app.version != 2:
        raise Http404

    command = ['venv/bin/python', '-m', 'manage', 'redeploy', app.name]
    if upgrade:
        command.insert(-1, '--upgrade')
    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(command, stdout=out, stderr=out)

    return render(request, 'wait_next.html', {
        'step': 'Upgrade' if upgrade else 'Redeploy',
        'pid': proc.pid,
        'next': reverse('show-result', args=[app_id])
    })

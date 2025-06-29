import subprocess

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from adminconsole.decorators import owner_of_app
from adminconsole.forms import PythonVersionForm
from adminconsole.models import App


@owner_of_app
def redeploy(request, app_id, upgrade=False):
    app = get_object_or_404(App, pk=app_id)
    if app.version != 2:
        raise Http404

    if request.method == 'POST':
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

    return render(request, 'generic/submit.html', {
        'page_title': f'Redeploy {app.name}',
        'button_text': 'Redeploy starten',
    })


@owner_of_app
def set_python_version(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    if app.version != 2:
        raise Http404

    success = False
    if request.method == 'POST':
        form = PythonVersionForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            success = True
    else:
        form = PythonVersionForm(instance=app)

    return render(request, 'python_version_form.html', {
        'form': form, 'success': success, 'app': app,
    })

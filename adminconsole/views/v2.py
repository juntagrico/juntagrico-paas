import subprocess

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from adminconsole.decorators import owner_of_app
from adminconsole.forms import PythonVersionForm
from adminconsole.models import App


@require_POST
@owner_of_app
def set_version(request, app_id):
    app = get_object_or_404(App, id=app_id)
    try:
        version = int(request.POST.get('version'))
        app.version = version
        app.save()
        if version == 1:
            messages.success(request, 'V1 aktiviert. Mache einen Rebuild um die Änderungen anzuwenden.')
        elif version == 2:
            messages.success(request, 'V2 aktiviert. Mache einen Redeploy um die Änderungen anzuwenden.')
    except ValueError:
        messages.error(request, 'Version nicht definiert.')
    return redirect('overview', app_id)


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

import subprocess

import psutil
from django.contrib import messages
from django.http import Http404, JsonResponse
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
        if app.staging_of:
            app.renew()

        command = ['venv/bin/python', '-m', 'manage', 'redeploy', app.name]
        if upgrade:
            command.insert(-1, '--upgrade')
        with open(app.log_file, 'wb') as out:
            proc = subprocess.Popen(command, stdout=out, stderr=out)

        return render(request, 'wait_redeploy.html', {
            'step': 'Upgrade' if upgrade else 'Redeploy',
            'url': reverse('progress', args=[app_id, proc.pid]),
            'pid': proc.pid,
            'next': reverse('show-result', args=[app_id])
        })

    return render(request, 'generic/submit.html', {
        'page_title': f'Redeploy {app.name}',
        'button_text': 'Redeploy starten',
    })


@owner_of_app
def show_progress(request, app_id, pid):
    app = get_object_or_404(App, pk=app_id)
    process = psutil.Process(int(pid))
    try:
        start = int(request.GET.get('s', 0))
    except ValueError:
        start = 0

    # parse log
    current_section = 0
    current_section_progress = 0
    current_title = None
    debug = None
    with open(app.log_file, 'r') as file:
        file.seek(start)
        while line := file.readline():
            line = line.lstrip()
            if line.startswith('# '):
                current_section += 1
                current_title = line[2:].rstrip()
            if line.startswith('Step '):
                debug = line
                step, current_title = line[5:].split(' : ')
                current_title = current_title.rstrip()
                try:
                    num, den = [int(num) for num in step.split('/')]
                    current_section_progress = num / den
                except ValueError:
                    pass
        read_until = file.tell()

    return JsonResponse({
        'status': process.status(),
        'section': current_section,
        'section_progress': current_section_progress,
        'title': current_title,
        'read': read_until,
        'debug': debug,
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

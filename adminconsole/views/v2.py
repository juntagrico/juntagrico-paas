import re
import subprocess  # nosec: B404

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from adminconsole.decorators import owner_of_app
from adminconsole.forms import PythonVersionForm, RedeployForm
from adminconsole.models import App
from adminconsole.util import pid_finished


def _spawn_redeploy(app, step_title, extra_args=None, copy_data=False):
    """Spawn a background redeploy command and return the wait page response."""
    if app.staging_of:
        app.renew()

    command = [settings.PYTHON_BIN, '-m', 'manage', 'redeploy']
    if extra_args:
        command.extend(extra_args)
    command.append(app.name)

    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(command, stdout=out, stderr=out)  # nosec: B603

    app_id = app.id
    progress_url = reverse('progress', args=[app_id, proc.pid])
    if copy_data:
        progress_url += '?copy_data=1'

    return render(
        None,  # request not needed for this template
        'flow/wait_redeploy.html',
        {
            'page_title': app.name,
            'step': step_title,
            'url': progress_url,
            'pid': proc.pid,
            'next': reverse('show-result', args=[app_id]),
        },
    )


@require_POST
@owner_of_app
def set_version(request, app_id):
    app = get_object_or_404(App, id=app_id)
    try:
        version = int(request.POST.get('version'))
    except (ValueError, TypeError):
        messages.error(request, 'Version nicht definiert.')
        return redirect('overview', app_id)

    old_version = app.version
    app.version = version
    app.save()
    messages.success(
        request, f'Infrastruktur-Version geändert von V{old_version} nach V{version}.'
    )

    return _spawn_redeploy(app, f'Version wechseln (V{old_version} → V{version})')


@owner_of_app
def redeploy(request, app_id, upgrade=False):
    app = get_object_or_404(App, pk=app_id)

    if app.version >= 3:
        return redeploy_with_form(request, app)

    if request.method == 'POST':
        extra_args = ['--upgrade'] if upgrade else []
        return _spawn_redeploy(app, 'Upgrade' if upgrade else 'Redeploy', extra_args)

    return render(
        request,
        'generic/submit.html',
        {
            'page_title': f'Redeploy {app.name}',
            'button_text': 'Redeploy starten',
        },
    )


def redeploy_with_form(request, app):
    """Redeploy flow with a form to adjust python version and branch before deploying."""
    if request.method == 'POST':
        form = RedeployForm(request.POST, app=app)
        if form.is_valid():
            # Save the adjusted values
            app.python_version = form.cleaned_data['python_version']
            app.set_branch(form.cleaned_data['branch'])
            app.wsgi = form.cleaned_data['wsgi']
            app.save()

            extra_args = []
            copy_data = form.cleaned_data.get('copy_data')
            if copy_data:
                extra_args.append('--copy-data')
            return _spawn_redeploy(app, 'Redeploy', extra_args, copy_data=copy_data)
    else:
        form = RedeployForm(app=app)

    return render(
        request,
        'app/redeploy_form.html',
        {
            'form': form,
            'app': app,
        },
    )


@owner_of_app
def show_progress(request, app_id, pid):
    app = get_object_or_404(App, pk=app_id)
    try:
        start = int(request.GET.get('s', 0))
    except ValueError:
        start = 0

    # parse log
    current_section = 0
    current_section_progress = None
    current_title = None
    docker_build_header = re.compile(r'^#(\d+)\s+\[([^\]]+)\]\s*(.*)$')
    docker_build_done = re.compile(r'^#(\d+)\s+(DONE|CACHED)')
    with open(app.log_file, 'r') as file:
        file.seek(start)
        while line := file.readline():
            line = line.lstrip()

            match = docker_build_header.match(line)
            if match:
                current_title = line
                continue

            match = docker_build_done.match(line)
            if match:
                current_section += 1
                continue

            if line.startswith('# '):
                current_section += 1
                current_section_progress = 0
                current_title = line[2:].rstrip()
            if line.startswith('Step '):
                step, current_title = line[5:].split(' : ')
                current_title = current_title.rstrip()
                try:
                    num, den = [int(num) for num in step.split('/')]
                    current_section_progress = num / den
                except ValueError:
                    pass
        read_until = file.tell()

    expected = None
    if start == 0:
        if app.version >= 3:
            base_steps = 5.1  # Docker Rebuild + Migrate + Collectstatic + Start + Collect Version
            docker_build_steps = 26  # v3 counts each docker build step
            clone_db_extra = 1 if (request.GET.get('copy_data') == '1') else 0
            expected = docker_build_steps + base_steps + clone_db_extra
        else:
            expected = 6.1  # v2 has an extra git pull step

    finished = pid_finished(pid)
    data = {
        'finished': finished,
        'section': current_section,
        'section_progress': current_section_progress,
        'expected_steps': expected,
        'title': current_title,
        'read': read_until,
    }
    if finished:
        # check if the setup completed fully
        data['setup_success'] = not app.installation_pending
    return JsonResponse(data)


@owner_of_app
def set_python_version(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    success = False
    if request.method == 'POST':
        form = PythonVersionForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            success = True
    else:
        form = PythonVersionForm(instance=app)

    return render(
        request,
        'app/python_version_form.html',
        {
            'form': form,
            'success': success,
            'app': app,
        },
    )

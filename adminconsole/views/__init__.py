import ast
import re
import subprocess

import docker
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django_otp import user_has_device
from docker.errors import APIError, DockerException

from adminconsole.decorators import owner_of_app
from adminconsole.forms import EnvForm, ProfileForm, BranchForm, AppEnvVarFormSet
from adminconsole.models import App
from adminconsole.util import pid_finished
from adminconsole.util.git import git_switch, git_current_branch
from adminconsole.views.generic import confirm_post, confirm_password, security_log, client_address


@login_required
def home(request):
    superuser = request.user.is_superuser
    if superuser:
        available_apps = App.objects.filter(staging_of__isnull=True).order_by('id')
    else:
        available_apps = request.user.app.filter(staging_of__isnull=True)
    number_of_apps = available_apps.count()
    if number_of_apps == 1 and not superuser:
        return redirect('overview', app_id=available_apps[0].id)

    return render(request, 'home.html', {
        'apps': available_apps,
        'can_add_app': number_of_apps < 1 or superuser,
    })


@owner_of_app
def overview(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    status = 'unknown'
    try:
        status = app.container.status
    except (DockerException, APIError) as e:
        messages.error(request, str(e))

    staging = app.staging_of is not None
    if staging and not app.code_dir.is_dir():
        # resume staging creation process
        return redirect('staging-git-clone', app_id=app.id)

    renderdict = {
        'app': app,
        'status': status,
        'staging': staging,
        'has_2fa': user_has_device(request.user),
    }
    return render(request, 'overview.html', renderdict)


@login_required
def pidcheck(request, pid):
    return JsonResponse({
        'finished': pid_finished(pid)
    })


@owner_of_app
def show_result(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    # parse log
    sections = {'Log': {'text': '', 'result': 1}}
    current = sections['Log']  # capture error output before the first section
    with open(app.log_file, 'r') as file:
        while line := file.readline():
            line = line.strip()
            if line.startswith('# '):
                line = line[2:]
                if line not in sections:
                    sections[line] = {'text': '', 'result': 1}
                current = sections[line]
            elif line.startswith('Return '):
                try:
                    current['result'] = int(line[7:])
                except ValueError:
                    pass
            else:
                if line[:2] in ['b"', "b'"]:
                    current['text'] += str(ast.literal_eval(line), 'utf-8')
                else:
                    current['text'] += line
                current['text'] += '\n'
    if not sections['Log']['text']:
        del sections['Log']
    return render(request, 'app/show_result.html',
                  {'app': app, 'sections': sections})


@owner_of_app
def env(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    app_env = app.env

    if request.method == 'POST':
        form = EnvForm(request.POST, instance=app_env)
        formset = AppEnvVarFormSet(request.POST, instance=app_env)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            with open(app.log_file, 'wb') as out:
                proc = subprocess.Popen(
                    [settings.PYTHON_BIN, '-m', 'manage', 'restart', app.name],
                    stdout=out, stderr=out
                )
            return render(request, 'app/wait_next.html', {
                'step': 'Einstellungen anwenden',
                'pid': proc.pid,
                'next': reverse('overview', args=[app.id])
            })
    else:
        form = EnvForm(instance=app_env)
        formset = AppEnvVarFormSet(instance=app_env)

    return render(request, 'app/env.html', {'form': form, 'formset': formset, 'app': app})


@owner_of_app
def change_branch(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    error = ''
    success = False
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            error = git_switch(app, form.cleaned_data['branch'])
            success = not error

    form = BranchForm(initial={'branch': git_current_branch(app)})
    return render(request, 'app/branch_form.html', {
        'form': form, 'success': success, 'error': error, 'app': app
    })


@owner_of_app
@confirm_post('Depotliste generieren', 'Depotliste erzeugen')
def generate_depot_list(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'generate_depot_list', '--force']
    container.exec_run(cmd)
    render_dict = {
        'step': 'Depotliste generieren',
        'next': reverse('overview', args=[app.id])
    }
    return render(request, 'app/done_next.html', render_dict)


@owner_of_app
def mailtexts(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'mailtexts']
    result = container.exec_run(cmd)
    result_text = result.output.decode('utf-8')
    if '(request)' in result_text:
        result_text = result_text.split('(request)')[1]
    # parse output
    sections = {'Log': {'text': '', 'result': 1}}
    current = sections['Log']  # capture error output before the first section
    for line in result_text.split('\n'):
        line = line.strip()
        if line.startswith('*** '):
            line = line.strip(' *')
            if line not in sections:
                sections[line] = {'text': '', 'result': 0}
            current = sections[line]
        else:
            current['text'] += line + '\n'
    if not sections['Log']['text']:
        del sections['Log']
    return render(
        request,
        'app/show_result.html',
        {'app': app, 'sections': sections, 'title': 'Email-Texte'},
    )


@owner_of_app
@confirm_password('Daten exportieren (JSON)', 'Exportieren')
def dumpdata(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    security_log.info('%s exports JSON of %s from %s', request.user, name, client_address(request))
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'dumpdata', '--natural-foreign', '--natural-primary', '-e', 'sessions']
    result = container.exec_run(cmd, stderr=False)
    response = HttpResponse(result.output.decode('utf-8'), content_type="application/json")
    response['Content-Disposition'] = f'attachment; filename={name}-{timezone.now().strftime("%y_%m_%d_%H_%M")}.json'
    return response


@owner_of_app
@confirm_password('Daten exportieren (SQL)', 'Exportieren')
def pgdump(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    security_log.info('%s exports SQL of %s from %s', request.user, app.name, client_address(request))
    db_user = settings.DATABASES['default']['USER']
    db_pw = settings.DATABASES['default']['PASSWORD']

    dump = subprocess.run(
        ['pg_dump', '-U', db_user, '--no-password', app.env.juntagrico_database_name],
        stdout=subprocess.PIPE, env={'PGPASSWORD': db_pw}
    )
    response = HttpResponse(dump.stdout.decode('utf-8'), content_type="application/sql")
    response['Content-Disposition'] = f'attachment; filename={app.name}-{timezone.now().strftime("%y_%m_%d_%H_%M")}.sql'
    return response


@owner_of_app
def logs(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    result_text = container.logs(tail=1000)
    result_text = result_text.decode('utf-8') 
    return render(request, 'app/show_result.html', {'app': app, 'sections': {
        'Docker Logs': {'text': result_text, 'result': 0},
    }})


@owner_of_app
def versions(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)

    python_version = None
    pip_version = None
    packages = []
    errors = []

    # Get Python version (python --version writes to stderr, so merge streams)
    try:
        result = container.exec_run(['python', '--version'], stderr=True)
        output = result.output.decode('utf-8').strip()
        if output:
            # "Python 3.11.18" -> "3.11.18"
            match = re.search(r'Python\s+(\S+)', output)
            if match:
                python_version = match.group(1)
            else:
                python_version = output
    except Exception as e:
        errors.append(f'Python-Version: {e}')

    # Get pip version
    try:
        result = container.exec_run(['pip', '--version'])
        output = result.output.decode('utf-8').strip()
        if result.exit_code == 0 or output:
            # "pip 26.2.2 from /usr/local/lib/python3.11/site-packages/pip (python 3.11)"
            match = re.search(r'pip\s+(\S+)', output)
            if match:
                pip_version = match.group(1)
            elif output:
                pip_version = output
    except Exception as e:
        errors.append(f'pip-Version: {e}')

    # Get installed packages
    try:
        result = container.exec_run(['pip', 'list', '--format', 'columns', '--disable-pip-version-check'])
        output = result.output.decode('utf-8').strip()
        if output:
            lines = output.split('\n')
            # Skip header lines (first 2 lines: header + separator)
            # "Package   Version"
            # "-------   -------"
            data_lines = lines[2:] if len(lines) > 2 else lines
            for line in data_lines:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    packages.append({'name': parts[0], 'version': parts[1]})
                elif len(parts) == 1:
                    packages.append({'name': parts[0], 'version': 'unknown'})
    except Exception as e:
        errors.append(f'Paketliste: {e}')

    return render(
        request,
        'app/versions.html',
        {
            'app': app,
            'python_version': python_version,
            'pip_version': pip_version,
            'packages': packages,
            'errors': errors,
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
    return render(request, 'profile.html', {'form': form})

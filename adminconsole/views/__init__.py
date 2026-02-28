import ast
import subprocess
from datetime import datetime
from time import sleep
from zoneinfo import ZoneInfo

import docker
import psutil
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from docker.errors import APIError, DockerException

from adminconsole.decorators import owner_of_app
from adminconsole.forms import EnvForm, DomainForm, ProfileForm, BranchForm
from adminconsole.models import App
from adminconsole.util import pid_finished
from adminconsole.util.git import git_switch, git_current_branch


@login_required
def home(request):
    superuser = request.user.is_superuser
    if superuser:
        available_apps = App.objects.all()
    else:
        available_apps = request.user.app.all()
    number_of_apps = available_apps.count()
    if number_of_apps == 1 and not superuser:
        return redirect('overview', app_id=available_apps[0].id)
    can_add_apps = number_of_apps < 1 or superuser
    renderdict = {
        'apps': available_apps.filter(staging_of__isnull=True),
        'staging_apps': available_apps.filter(staging_of__isnull=False),
        'can_add_app': can_add_apps,
    }
    return render(request, 'home.html', renderdict)


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
        'staging': staging
    }
    return render(request, 'overview.html', renderdict)


@login_required
def pidcheck(request, pid):
    return JsonResponse({
        'finished': pid_finished(pid)
    })


@owner_of_app
def reload(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'rebuild_docker', app.name], stdout=out, stderr=out)
    render_dict = {
        'step': 'Redeploy',
        'pid': proc.pid,
        'next': reverse('show-result', args=[app_id])
    }
    return render(request, 'wait_next.html', render_dict)


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
    return render(request, 'show_result.html',
                  {'app': app, 'sections': sections})


@owner_of_app
def rebuild_image(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'rebuild_image', app.name, str(app.port)],
                                stdout=out, stderr=out)
    render_dict = {
        'step': 'Rebuild',
        'pid': proc.pid,
        'next': reverse('show-result', args=[app.id])
    }
    return render(request, 'wait_next.html', render_dict)


@owner_of_app
def show_log(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    with open(app.log_file, 'r') as file:
        b_texts = file.readlines()
        texts = [str(eval(b_text), 'utf-8') if b_text.startswith('b') else b_text for b_text in b_texts]
        result_text = '\n'.join(texts)
    return render(request, 'mailtexts.html', {'app': app, 'text': result_text})


@owner_of_app
def env(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    app_env = app.env

    if request.method == 'POST':
        form = EnvForm(request.POST, instance=app_env)
        if form.is_valid():
            form.save()
            if app.version == 2:
                with open(app.log_file, 'wb') as out:
                    proc = subprocess.Popen(
                        ['venv/bin/python', '-m', 'manage', 'restart', app.name],
                        stdout=out, stderr=out
                    )
                return render(request, 'wait_next.html', {
                    'step': 'Einstellungen anwenden',
                    'pid': proc.pid,
                    'next': reverse('overview', args=[app.id])
                })

            return redirect('/env/restart/' + str(app_id) + '/')
    else:
        form = EnvForm(instance=app_env)

    return render(request, 'env.html', {'form': form})


@owner_of_app
def env_restart(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    app_env = app.env
    fn = app.dir / 'build' / f'{name}.env'
    with open(fn, 'w') as out:
        out.write('JUNTAGRICO_DEBUG=False\n ')
        out.write('JUNTAGRICO_DATABASE_ENGINE=django.db.backends.postgresql\n ')
        for field in app_env._meta.get_fields():
            if hasattr(field, 'verbose_name'):
                if field.verbose_name != 'VARIOUS':
                    out.write(field.verbose_name)
                    out.write('=')
                out.write(str(getattr(app_env, field.name)))
                out.write('\n')
    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'reload_env', name, str(app.port)], stdout=out,
                                stderr=out)
    render_dict = {
        'step': 'Einstellungen anwenden',
        'pid': proc.pid,
        'next': reverse('overview', args=[app.id])
    }
    return render(request, 'wait_next.html', render_dict)


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
    return render(request, 'branch_form.html', {
        'form': form, 'success': success, 'error': error, 'app': app
    })


@owner_of_app
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
    return render(request, 'done_next.html', render_dict)


@owner_of_app
def domain_form(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    port = str(app.port)
    if request.method == 'POST':
        form = DomainForm(request.POST)
        if form.is_valid():
            domain = form.cleaned_data['domain']
            with open(app.log_file, 'wb') as out:
                proc = subprocess.Popen(
                    ['venv/bin/python', '-m', 'manage', 'add_domain', app.name, port, domain],
                    stdout=out, stderr=out
                )
            return redirect('/dom/add/' + str(proc.pid) + '/')
    else:
        form = DomainForm()

    return render(request, 'domain_form.html', {'form': form})


@login_required
def add_domain(request, pid):
    render_dict = {
        'step': 'Domain hinzufügen',
        'pid': pid,
        'next': '/'
    }
    return render(request, 'wait_next.html', render_dict)


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
    return render(request, 'show_result.html', {'app': app, 'sections': sections})


@owner_of_app
def dumpdata(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'dumpdata', '--natural-foreign', '--natural-primary', '-e', 'sessions']
    result = container.exec_run(cmd, stderr=False)
    response = HttpResponse(result.output.decode('utf-8'), content_type="application/json")
    response['Content-Disposition'] = f'attachment; filename={name}-{timezone.now().strftime("%y_%m_%d_%H_%M")}.json'
    return response


@owner_of_app
def pgdump(request, app_id):
    app = get_object_or_404(App, pk=app_id)
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
    return render(request, 'show_result.html', {'app': app, 'sections': {
        'Docker Logs': {'text': result_text, 'result': 0},
    }})


@owner_of_app
def versions(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    result1 = container.exec_run(['python', '--version'])
    result2 = container.exec_run(['pip', 'freeze'])
    result_text = result1.output.decode('utf-8') + "\n" + result2.output.decode('utf-8')
    return render(request, 'show_result.html', {'app': app, 'sections': {
        'Installierte App Versionen': {'text': result_text, 'result': result1.exit_code + result2.exit_code},
    }})


@owner_of_app
def migrate(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'migrate']
    result = container.exec_run(cmd)
    result_text = result.output.decode('utf-8')
    return render(request, 'show_result.html', {'app': app, 'sections': {
        'Django Migrate': {'text': result_text, 'result': result.exit_code},
    }})


@owner_of_app
def collectstatic(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'collectstatic', '--noinput', '-c']
    result = container.exec_run(cmd)
    result_text = result.output.decode('utf-8')
    return render(request, 'show_result.html', {'app': app, 'sections': {
        'Django Collectstatic': {'text': result_text, 'result': result.exit_code},
    }})


@owner_of_app
def restart(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    container.restart()
    sleep(3)
    result_text = container.attrs['State']['StartedAt'].split('.')[0]+' UTC+0000'
    dt = datetime.strptime(result_text, '%Y-%m-%dT%H:%M:%S %Z%z')
    dt = dt.astimezone(ZoneInfo('Europe/Zurich'))
    result_text = dt.strftime('%d-%m-%Y %H:%M:%S %Z%z')
    return render(request, 'show_result.html', {'app': app, 'sections': {
        'Docker Restart': {'text': result_text, 'result': 0},
    }})

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

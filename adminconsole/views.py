import re
import subprocess
from datetime import datetime

import docker
import psutil
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.utils import timezone as django_timezone
from django.shortcuts import render, redirect, get_object_or_404
from pytz import timezone

from adminconsole.decorators import owner_of_app
from adminconsole.forms import EnvForm, DomainForm, ProfileForm, BranchForm
from adminconsole.models import App


@login_required
def home(request):
    superuser = request.user.is_superuser
    if superuser:
        apps = App.objects.all()
    else:
        apps = request.user.app.all()
    number_of_apps = apps.count()
    if number_of_apps == 1 and not superuser:
        return redirect('overview', app_id=apps[0].id)
    can_add_apps = number_of_apps < 1 or superuser
    renderdict = {
        'apps': apps,
        'can_add_app': can_add_apps,
    }
    return render(request, 'home.html', renderdict)


@owner_of_app
def overview(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    renderdict = {
        'app': app,
    }
    return render(request, 'overview.html', renderdict)


@login_required
def pidcheck(request, pid):
    p = psutil.Process(int(pid))
    data = {
        'status': p.status()
    }
    return JsonResponse(data)


@owner_of_app
def reload(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    fn = '/var/django/projects/' + name + '.txt'
    with open(fn, 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'rebuild_docker', name], stdout=out, stderr=out)
    render_dict = {
        'step': 'install requirements commit image collectstatic and migrate',
        'pid': proc.pid,
        'next': reverse('redeploy-result', args=[app_id])
    }
    return render(request, 'wait_next.html', render_dict)


@owner_of_app
def redeploy_result(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    fn = '/var/django/projects/' + name + '.txt'
    # parse log
    sections = {
        'Fetch latest code': {'text': ''},
        'Install Requirements': {'text': ''},
        'Commit to Docker Container': {'text': ''},
        'Restart Docker Container': {'text': ''},
        'Django Migrate': {'text': ''},
        'Django Collectstatic': {'text': ''},
        'Restart Docker Container again': {'text': ''},
    }
    current = None
    with open(fn, 'r') as file:
        while line := file.readline().strip():
            if line in sections:
                current = sections[line]
            elif current is not None:
                current['text'] += str(eval(line), 'utf-8') if line.startswith('b') else line
                current['text'] += '\n'
    return render(request, 'redeploy/result.html',
                  {'app': app, 'sections': sections})


@owner_of_app
def rebuild_image(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    fn = '/var/django/projects/' + name + '.txt'
    with open(fn, 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'rebuild_image', name, str(app.port)],
                                stdout=out, stderr=out)
    render_dict = {
        'step': 'git pull, rebuild docker image with latest requirements, restart container, migrate and collectstatic',
        'pid': proc.pid,
        'next': '/showlog/' + str(app_id) + '/'
    }
    return render(request, 'wait_next.html', render_dict)


@owner_of_app
def show_log(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    fn = '/var/django/projects/' + name + '.txt'
    with open(fn, 'r') as file:
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
            data = form.cleaned_data
            data.update(app_env.__dict__)
            return redirect('/env/restart/' + str(app_id) + '/')
    else:
        form = EnvForm(instance=app_env)
    return render(request, 'env.html', {'form': form})


@owner_of_app
def env_restart(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    app_env = app.env
    fn = '/var/django/projects/' + name + '/build/' + name + '.env'
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
    fn = '/var/django/projects/' + name + '.txt'
    with open(fn, 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'reload_env', name, str(app.port)], stdout=out,
                                stderr=out)
    render_dict = {
        'step': 'env reload',
        'pid': proc.pid,
        'next': reverse('overview', args=[app.id])
    }
    return render(request, 'wait_next.html', render_dict)


@owner_of_app
def change_branch(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    cdir = '/var/django/projects/' + name + '/code'
    error = ''
    success = False
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            branch = re.sub('[?*[@#$;&~^: ]', '', form.cleaned_data['branch'])
            proc = subprocess.run(['git', 'fetch', 'origin', branch],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
            if proc.returncode != 0:
                error += proc.stdout.decode()
            else:
                proc = subprocess.run(['git', 'checkout', '-B', branch],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
                if proc.returncode != 0:
                    error += proc.stdout.decode()
                else:
                    proc = subprocess.run(['git', 'branch', '-u', 'origin/' + branch, branch],
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
                    if proc.returncode != 0:
                        error += proc.stdout.decode()
                    else:
                        success = True
    proc = subprocess.Popen(['git', 'branch', '--show-current'], stdout=subprocess.PIPE, cwd=cdir)
    branch = proc.stdout.read().decode().strip()
    form = BranchForm(initial={'branch': branch})
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
        'step': 'depot liste generiert ',
        'next': reverse('overview', args=[app.id])
    }
    return render(request, 'done_next.html', render_dict)


@owner_of_app
def domain_form(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    port = str(app.port)
    if request.method == 'POST':
        form = DomainForm(request.POST)
        if form.is_valid():
            fn = '/var/django/projects/' + name + '.txt'
            domain = form.cleaned_data['domain']
            with open(fn, 'wb') as out:
                proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'add_domain', name, port, domain],
                                        stdout=out,
                                        stderr=out)
            return redirect('/dom/add/' + str(proc.pid) + '/')
    else:
        form = DomainForm()

    return render(request, 'domain_form.html', {'form': form})


@login_required
def add_domain(request, pid):
    render_dict = {
        'step': 'add domain',
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
    return render(request, 'mailtexts.html', {'app': app, 'text': result_text})


@owner_of_app
def dumpdata(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'dumpdata', '--natural-foreign', '--natural-primary', '-e', 'sessions']
    result = container.exec_run(cmd, stderr=False)
    response = HttpResponse(result.output.decode('utf-8'), content_type="application/json")
    response['Content-Disposition'] = f'attachment; filename={name}-{django_timezone.now().strftime("%y_%m_%d_%H_%M")}.json'
    return response


@owner_of_app
def logs(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    result_text = container.logs(tail=1000)
    result_text = result_text.decode('utf-8') 
    return render(request, 'mailtexts.html', {'app': app, 'text': result_text})


@owner_of_app
def versions(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    result1 = container.exec_run(['python', '--version'])
    result2 = container.exec_run(['pip', 'freeze'])
    result_text = result1.output.decode('utf-8') + "\n" + result2.output.decode('utf-8')
    return render(request, 'mailtexts.html', {'app': app, 'text': result_text})


@owner_of_app
def migrate(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'migrate']
    result = container.exec_run(cmd)
    result_text = result.output.decode('utf-8')
    return render(request, 'mailtexts.html', {'app': app, 'text': result_text})


@owner_of_app
def collectstatic(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'collectstatic', '--noinput', '-c']
    result = container.exec_run(cmd)
    result_text = result.output.decode('utf-8')
    return render(request, 'mailtexts.html', {'app': app, 'text': result_text})


@owner_of_app
def restart(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    container.restart()
    result_text = container.attrs['State']['StartedAt'].split('.')[0]+' UTC+0000'
    dt = datetime.strptime(result_text, '%Y-%m-%dT%H:%M:%S %Z%z')
    dt = dt.astimezone(timezone('CET'))
    result_text = dt.strftime('%d-%m-%Y %H:%M:%S %Z%z')
    return render(request, 'mailtexts.html', {'app': app, 'text': result_text})

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

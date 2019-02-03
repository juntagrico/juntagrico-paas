import subprocess
import psutil
import docker

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from adminconsole.models import App
from adminconsole.forms import EnvForm, DomainForm


@login_required
def home(request):
    apps = request.user.app.all()
    number_of_apps = apps.count()
    superuser = request.user.is_superuser
    can_add_apps = number_of_apps < 1 or superuser
    renderdict = {
        'apps': apps,
        'can_add_app': superuser,
    }
    return render(request, 'home.html', renderdict)


@login_required
def pidcheck(request, pid):
    p = psutil.Process(int(pid))
    data = {
        'status': p.status()
    }
    return JsonResponse(data)


@login_required
def reload(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    fn = '/var/django/projects/' + name + '.txt'
    with open(fn, 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'rebuild_docker', name], stdout=out, stderr=out)
    render_dict = {
        'step': 'rebuild docker and start',
        'pid': proc.pid,
        'next': '/'
    }
    return render(request, 'wait_next.html', render_dict)


@login_required
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


@login_required
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
        'next': '/'
    }
    return render(request, 'wait_next.html', render_dict)


@login_required
def generate_depot_list(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'generate_depot_list', '--force']
    container.exec_run(cmd)
    render_dict = {
        'step': 'depot liste generiert ',
        'next': '/'
    }
    return render(request, 'done_next.html', render_dict)


@login_required
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

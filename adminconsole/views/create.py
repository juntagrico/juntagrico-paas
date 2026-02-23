import os
import subprocess

from cookiecutter.main import cookiecutter

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.utils.safestring import mark_safe

from adminconsole.config import Config
from adminconsole.decorators import owner_of_app
from adminconsole.models import App, AppEnv
from adminconsole.forms import ProjectForm, EnvForm, AppForm, OverwriteAppForm
from adminconsole.util.create_app import find_port, create_database


@login_required
def app_form(request):
    user = request.user
    if request.method == 'POST':
        app = App(user=user, port=find_port())
        form = AppForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            return redirect('ca-git-clone', app_id=app.id)
    else:
        form = AppForm()

    return render(request, 'create/app_form.html', {'form': form})


@owner_of_app
def overwrite_app(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    if request.method == 'POST':
        form = OverwriteAppForm(request.POST)
        if form.is_valid():
            if form.cleaned_data['overwrite']:
                return redirect('ca-cookiecutter', app_id=app_id)
            return redirect('ca-init-db', app_id=app_id)
    else:
        form = OverwriteAppForm()

    files = os.listdir(app.code_dir)
    if '.git' in files:
        files.remove('.git')

    if not files:
        # if repo is empty, move on with cookiecutter
        return redirect('ca-cookiecutter', app_id=app_id)

    # Otherwise ask what to do
    return render(request, 'create/overwrite.html', {
        'form': form,
        'files': files,
    })


@owner_of_app
def cookiecutter_form(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    url = 'https://github.com/juntagrico/juntagrico-science-django-cookiecutter'
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            cookiecutter(url, no_input=True, extra_context=data, output_dir=app.dir, overwrite_if_exists=True)
            if Config.test_localhost():
                return redirect('ca-init-db', app_id=app_id)
            return redirect('ca-git-push', app_id=app_id)
    else:
        form = ProjectForm(initial={'project_slug': app.name})

    return render(request, 'create/ck.html', {'form': form})


@owner_of_app
def init_db(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    app_env = AppEnv.objects.create(app=app)
    create_database(app_env, name, name)
    return redirect('ca-create-env', app_id=app_id)


@owner_of_app
def env_form(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    if request.method == 'POST':
        form = EnvForm(request.POST, instance=app.env)
        if form.is_valid():
            form.save()
            return redirect('ca-init-domain', app_id=app_id)
    else:
        form = EnvForm()
    return render(request, 'env.html', {'form': form})


@owner_of_app
def init_domain(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    domain = f'{app.name}.juntagrico.science'
    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(
            ['venv/bin/python', '-m', 'manage', 'add_domain', app.name, str(app.port), domain],
            stdout=out, stderr=out
        )

    return render(request, 'generic/wait_next_submit.html', {
        'step': 'Domain einrichten',
        'pid': proc.pid,
        'next': reverse('ca-init-cronjob', args=[app_id])
    })


@owner_of_app
def init_cronjob(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(
            ['venv/bin/python', '-m', 'manage', 'install_cronjob', app.name],
            stdout=out, stderr=out
        )

    render_dict = {
        'step': 'Cronjob einrichten',
        'pid': proc.pid,
        'next': reverse('ca-build', args=[app_id])
    }
    return render(request, 'wait_next.html', render_dict)


@owner_of_app
def build(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(
            ['venv/bin/python', '-m', 'manage', 'redeploy', app.name],
            stdout=out, stderr=out
        )

    return render(request, 'wait_redeploy.html', {
        'step': 'docker build und starten',
        'url': reverse('progress', args=[app_id, proc.pid]),
        'pid': proc.pid,
        'next': reverse('ca-create-admin', args=[app.id])
    })


@owner_of_app
def create_admin(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    password = app.env.juntagrico_database_password

    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(
            ['venv/bin/python', '-m', 'manage', 'create_admin', app.name, password],
            stdout=out, stderr=out
        )

    render_dict = {
        'step': 'Admin erstellen - Notiere dieses Passwort: ' + password,
        'pid': proc.pid,
        'next': reverse('overview', args=[app.id])
    }
    return render(request, 'wait_next.html', render_dict)

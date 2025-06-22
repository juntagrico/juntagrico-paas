import os
import subprocess

from cookiecutter.main import cookiecutter

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.urls import reverse
from django.utils.safestring import mark_safe

from adminconsole.config import Config
from adminconsole.decorators import owner_of_app
from adminconsole.models import App, AppEnv
from adminconsole.forms import ProjectForm, EnvForm, AppForm, OverwriteAppForm
from adminconsole.util import generate_password
from adminconsole.util.create_app import find_port


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

    files = os.listdir(app.dir / 'code')
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
    password = generate_password()
    with connection.cursor() as cursor:
        cursor.execute("CREATE DATABASE " + name)
        cursor.execute("CREATE USER " + name + " WITH PASSWORD '" + password + "'")
        cursor.execute("ALTER ROLE " + name + " SET client_encoding TO 'utf8'")
        cursor.execute("ALTER ROLE " + name + " SET default_transaction_isolation TO 'read committed'")
        cursor.execute("ALTER ROLE " + name + " SET timezone TO 'CET'")
        cursor.execute("GRANT ALL PRIVILEGES ON DATABASE " + name + " TO " + name)
    app_env = AppEnv.objects.create(app=app)
    app_env.juntagrico_database_host = 'localhost'
    app_env.juntagrico_database_name = name
    app_env.juntagrico_database_password = password
    app_env.juntagrico_database_port = '5432'
    app_env.juntagrico_database_user = name
    app_env.save()
    return redirect('ca-admin-pw', app_id=app_id)


@owner_of_app
def admin_password(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    render_dict = {
        'step': mark_safe('Admin Passwort<br/>' + app.env.juntagrico_database_password + '<br/>Unbedingt aufschreiben!'),
        'next': reverse('ca-create-env', args=[app_id])
    }
    return render(request, 'done_next.html', render_dict)


@owner_of_app
def env_form(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    url = 'https://github.com/juntagrico/juntagrico-science-cookiecutter-infra'
    if Config.test_localhost():
        uri = app.name + '.localhost'
    else:
        uri = app.name + '.juntagrico.science'
    app_env = app.env
    if request.method == 'POST':
        form = EnvForm(request.POST, instance=app_env)
        if form.is_valid():
            form.save()
            data = form.cleaned_data
            data.update(app_env.__dict__)
            data.update({
                'admin_portal_url': uri,
                'project_name': app.name,
                'port': app.port,
            })
            cookiecutter(url, no_input=True, extra_context=data, output_dir=app.dir, overwrite_if_exists=True)
            return redirect('/ca/env/dist')
    else:
        form = EnvForm()
    return render(request, 'env.html', {'form': form})


@owner_of_app
def env_dist2(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    with open(app.dir + '.txt', 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'dist_infra', app.name],
                                stdout=out, stderr=out)

    render_dict = {
        'step': 'umgebung distributen und https einrichten',
        'pid': proc.pid,
        'next': reverse('ca-build-docker', args=[app_id])
    }
    return render(request, 'wait_next.html', render_dict)


@owner_of_app
def docker2(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    port = str(app.port)
    env = app.env
    passw = env.juntagrico_database_password
    with open(app.dir + '.txt', 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'build_docker2', app.name, passw, port],
                                stdout=out, stderr=out)
    render_dict = {
        'step': 'docker build und start',
        'pid': proc.pid,
        'next': reverse('home')
    }
    return render(request, 'wait_next.html', render_dict)

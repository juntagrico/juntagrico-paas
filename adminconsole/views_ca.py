import subprocess

from cookiecutter.main import cookiecutter

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import connection

from adminconsole.config import Config
from adminconsole.models import App, AppEnv
from adminconsole.forms import ProjectForm, EnvForm, AppForm
from adminconsole.util import generate_password
from adminconsole.util.create_app import find_port


@login_required
def import_app(request):
    request.session['import'] = True
    return create_app(request)


@login_required
def create_app(request):
    request.session['import'] = False
    user = request.user
    if Config.test_localhost():
        return redirect('/ca/af')
    if not hasattr(user, 'githubkey'):
        return redirect('/github/request')
    return redirect('/ca/repo')


@login_required
def app_form(request):
    user = request.user
    clone_url = request.session.get('git_clone_url', '')
    if request.method == 'POST':
        port = find_port()
        app = App(git_clone_url=clone_url,
                  user=user,
                  port=port)
        form = AppForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            request.session['git_clone_url'] = None
            request.session['app'] = app.id
            return redirect('/ca/clonerepo')
    else:
        form = AppForm()

    return render(request, 'app_form.html', {'form': form})


@login_required
def cookiecutter_form(request):
    app = get_object_or_404(App, pk=request.session['app'])
    directory = '/var/django/projects/' + app.name
    url = 'https://github.com/juntagrico/juntagrico-science-django-cookiecutter'
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            cookiecutter(url, no_input=True, extra_context=data, output_dir=directory, overwrite_if_exists=True)
            if Config.test_localhost():
                return redirect('/ca/db')
            return redirect('/git/push')
    else:
        form = ProjectForm(initial={'project_slug': app.name})

    return render(request, 'ck.html', {'form': form})


@login_required
def init_db(request):
    app = get_object_or_404(App, pk=request.session['app'])
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
    return redirect('/ca/ap')

@login_required
def admin_password(request):
    app = get_object_or_404(App, pk=request.session['app'])
    app_env = app.env
    render_dict = {
        'step': 'Admin Passwort<br/>' + app_env.juntagrico_database_password + '<br/>Unbedingt aufschreiben!',
        'next': '/ca/env/form'
    }
    return render(request, 'done_next.html', render_dict)


@login_required
def env_form(request):
    app = get_object_or_404(App, pk=request.session['app'])
    directory = '/var/django/projects/' + app.name
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
            cookiecutter(url, no_input=True, extra_context=data, output_dir=directory, overwrite_if_exists=True)
            return redirect('/ca/env/dist')
    else:
        form = EnvForm()
    return render(request, 'env.html', {'form': form})


@login_required
def env_dist2(request):
    app = get_object_or_404(App, pk=request.session['app'])
    name = app.name
    fn = '/var/django/projects/' + name + '.txt'
    with open(fn, 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'dist_infra', name], stdout=out, stderr=out)

    render_dict = {
        'step': 'umgebung distributen und https einrichten',
        'pid': proc.pid,
        'next': '/ca/docker'
    }
    return render(request, 'wait_next.html', render_dict)


@login_required
def docker2(request):
    app = get_object_or_404(App, pk=request.session['app'])
    name = app.name
    port = str(app.port)
    env = app.env
    passw = env.juntagrico_database_password
    fn = '/var/django/projects/' + name + '.txt'
    with open(fn, 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'build_docker2', name, passw, port], stdout=out,
                                stderr=out)
    render_dict = {
        'step': 'docker build und start',
        'pid': proc.pid,
        'next': '/'
    }
    request.session['app'] = None
    return render(request, 'wait_next.html', render_dict)

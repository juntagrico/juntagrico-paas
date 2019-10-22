import random
import string
import subprocess
import psutil
import docker

from urllib import request as r, parse
from cookiecutter.main import cookiecutter
from github import Github

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db import connection

from adminconsole.decorators import owner_of_app
from adminconsole.models import App, GitHubKey, AppEnv
from adminconsole.forms import EnvForm, DomainForm, AppForm, ProjectForm
from adminconsole.util.create_app import find_port


@login_required
def home(request):
    superuser = request.user.is_superuser
    if superuser:
        apps = App.objects.all()
    else:
        apps = request.user.app.all()
    number_of_apps = apps.count()
    can_add_apps = number_of_apps < 1 or superuser
    renderdict = {
        'apps': apps,
        'can_add_app' : can_add_apps,
    }
    return render(request, 'home.html', renderdict)



def github_request(request):
    return redirect('https://github.com/login/oauth/authorize?client_id=b420b562ea569fd26b6e&scope=public_repo')


def github_callback(request):
    code = request.GET.get('code')
    data_dict = {'code': code,
                 'client_id': 'b420b562ea569fd26b6e',
                 'client_secret': '40054b662fedbb506539aa8ab91031ca21383cb2'
                 }
    data = parse.urlencode(data_dict).encode()
    req = r.Request('https://github.com/login/oauth/access_token', data=data)
    resp = r.urlopen(req)
    key = str(resp.read()).split('&')[0].split('=')[1]
    GitHubKey.objects.create(user=request.user, key=key)
    return redirect('/ca/repo')


@login_required
def import_app(request):
    request.session['import'] = True
    return create_app(request)


@login_required
def create_app(request):
    user = request.user
    if not hasattr(user, 'githubkey'):
        return redirect('/github/request')
    return redirect('/ca/repo')


@login_required
def select_repo(request):
    key = request.user.githubkey.key
    g = Github(key)
    repos = g.get_user().get_repos()
    if request.method == 'POST':
        selected_repo = request.POST.get('repo')
        for repo in repos:
            if repo.name == selected_repo:
                request.session['git_clone_url'] = repo.clone_url
                return redirect('/ca/af')
    render_dict = {
        'repos': repos,
    }
    return render(request, 'repos.html', render_dict)


@login_required
def app_form(request):
    user = request.user
    clone_url = request.session['git_clone_url']
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
def clone_repo(request):
    key = request.user.githubkey.key
    app = get_object_or_404(App, pk=request.session['app'])
    output = []
    dir = '/var/django/projects/' + app.name
    url = 'https://' + key + ':x-oauth-basic@' + app.git_clone_url[8:]
    proc = subprocess.run(['mkdir', dir], stdout=subprocess.PIPE)
    output.append(str(proc.stdout))
    proc = subprocess.run(['mkdir', 'static'], stdout=subprocess.PIPE, cwd=dir)
    output.append(str(proc.stdout))
    proc = subprocess.run(['mkdir', 'media'], stdout=subprocess.PIPE, cwd=dir)
    output.append(str(proc.stdout))
    proc = subprocess.run(['git', 'clone', url, 'code'], stdout=subprocess.PIPE, cwd=dir)
    output.append(str(proc.stdout))
    render_dict = {
        'step': 'Repo Klonen',
        'next': '/ck/form',
    }
    if request.session.get('import', False):
        render_dict['next'] = '/ca/db'
    return render(request, 'done_next.html', render_dict)


@login_required
def cookiecutter_form(request):
    app = get_object_or_404(App, pk=request.session['app'])
    dir = '/var/django/projects/' + app.name
    url = 'https://github.com/juntagrico/juntagrico-science-django-cookiecutter'
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            cookiecutter(url, no_input=True, extra_context=data, output_dir=dir, overwrite_if_exists=True)
            return redirect('/git/push')
    else:
        form = ProjectForm(initial={'project_slug': app.name})

    return render(request, 'ck.html', {'form': form})


@login_required
def git_push(request):
    key = request.user.githubkey.key
    app = get_object_or_404(App, pk=request.session['app'])
    dir = '/var/django/projects/' + app.name + '/code'
    output = []
    proc = subprocess.run(['git', 'add', '.', '--all'], stdout=subprocess.PIPE, cwd=dir)
    output.append(str(proc.stdout))
    proc = subprocess.run(['git', 'commit', '-a', '-m', '"adminconsole"'], stdout=subprocess.PIPE, cwd=dir)
    output.append(str(proc.stdout))
    proc = subprocess.run(['git', 'push'], stdout=subprocess.PIPE, cwd=dir)
    output.append(str(proc.stdout))
    render_dict = {
        'step': 'Cokkiecutter anwenden und repo pushen',
        'next': '/ca/db'
    }
    return render(request, 'done_next.html', render_dict)


@login_required
def init_db(request):
    app = get_object_or_404(App, pk=request.session['app'])
    name = app.name
    password = ''.join(random.choice(string.ascii_uppercase + string.digits) for x in range(20))
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
    return redirect('/ca/env/form')


@login_required
def env_form(request):
    app = get_object_or_404(App, pk=request.session['app'])
    dir = '/var/django/projects/' + app.name
    url = 'https://github.com/juntagrico/juntagrico-science-cookiecutter-infra'
    app_env = app.env
    if request.method == 'POST':
        form = EnvForm(request.POST, instance=app_env)
        if form.is_valid():
            form.save()
            data = form.cleaned_data
            data.update(app_env.__dict__)
            data.update({
                'project_name': app.name,
                'port': app.port,
            })
            cookiecutter(url, no_input=True, extra_context=data, output_dir=dir, overwrite_if_exists=True)
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
        'step': 'rebuild docker and start',
        'pid': proc.pid,
        'next': '/'
    }
    return render(request, 'wait_next.html', render_dict)


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
        'next': '/'
    }
    return render(request, 'wait_next.html', render_dict)


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
        'next': '/'
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
    return render(request, 'mailtexts.html', {'text': result_text})


@owner_of_app
def logs(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    result_text = container.logs()
    result_text = result_text.decode('utf-8') 
    return render(request, 'mailtexts.html', {'text': result_text})


@owner_of_app
def migrate(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'migrate']
    result = container.exec_run(cmd)
    result_text = result.output.decode('utf-8')
    return render(request, 'mailtexts.html', {'text': result_text})


@owner_of_app
def collectstatic(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'collectstatic', '--noinput', '-c']
    result = container.exec_run(cmd)
    result_text = result.output.decode('utf-8')
    return render(request, 'mailtexts.html', {'text': result_text})


@owner_of_app
def restart(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    container.restart()
    result_text = str(container.stats(stream=False))
    result_text = result_text.decode('utf-8')
    return render(request, 'mailtexts.html', {'text': result_text})

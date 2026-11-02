import os
import subprocess

from cookiecutter.main import cookiecutter
from django.conf import settings

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse

from adminconsole.config import Config
from adminconsole.decorators import owner_of_app
from adminconsole.models import App, AppEnv, AppCronjob
from adminconsole.forms import ProjectForm, EnvForm, AppForm, OverwriteAppForm
from adminconsole.util.create_app import find_port, create_database
from adminconsole.views.generic import confirm_post


@login_required
def app_form(request):
    user = request.user
    if request.method == 'POST':
        app = App(user=user, port=find_port())
        form = AppForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            return redirect('github-select', app_id=app.id)
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

    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            # pinned version and no hooks: the template must not run code on this server
            cookiecutter(
                settings.COOKIECUTTER_URL,
                checkout=settings.COOKIECUTTER_COMMIT,
                accept_hooks=False,
                no_input=True,
                extra_context=data,
                output_dir=app.dir,
                overwrite_if_exists=True,
            )
            if Config.test_localhost():
                return redirect('ca-init-db', app_id=app_id)
            return redirect('ca-git-push', app_id=app_id)
    else:
        form = ProjectForm(initial={'project_slug': app.name})

    return render(request, 'create/ck.html', {'form': form})


@owner_of_app
@confirm_post('Datenbank erstellen', 'Datenbank erstellen')
def init_db(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    app_env = AppEnv.objects.get_or_create(app=app)[0]
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
        form = EnvForm(instance=app.env)
    return render(request, 'env.html', {'form': form})


@owner_of_app
@confirm_post('Domain einrichten', 'Domain einrichten')
def init_domain(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    domain = app.domains.get_or_create(name=f'{app.name}{settings.APPS_DOMAIN}')[0]
    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(
            [settings.PYTHON_BIN, '-m', 'manage', 'add_domain', domain.name],
            stdout=out, stderr=out
        )

    return render(request, 'generic/wait_next_submit.html', {
        'step': 'Domain einrichten',
        'pid': proc.pid,
        'next': reverse('ca-init-cronjob', args=[app_id])
    })


@owner_of_app
@confirm_post('Cronjob einrichten', 'Cronjob einrichten')
def init_cronjob(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    # Set default cronjobs for new apps: depot_list_no_future with daily timing
    from adminconsole.models import get_available_cronjobs
    available = get_available_cronjobs(app.name)
    for cj_def in available:
        if cj_def.get('group') == 'depot_list' and '--no-future' in cj_def.get('command', ''):
            AppCronjob.objects.get_or_create(
                app=app,
                cronjob_id=cj_def['id'],
                defaults={
                    'hour': cj_def.get('default_hour', 23),
                    'minute': cj_def.get('default_minute', 50),
                }
            )
            break

    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(
            [settings.PYTHON_BIN, '-m', 'manage', 'install_cronjob', app.name],
            stdout=out, stderr=out
        )

    return render(request, 'generic/wait_next_submit.html', {
        'step': 'Cronjob einrichten',
        'pid': proc.pid,
        'next': reverse('ca-build', args=[app_id])
    })


@owner_of_app
@confirm_post('Docker build und starten', 'Build starten')
def build(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(
            [settings.PYTHON_BIN, '-m', 'manage', 'redeploy', app.name],
            stdout=out, stderr=out
        )

    return render(request, 'generic/wait_redeploy_submit.html', {
        'step': 'docker build und starten',
        'url': reverse('progress', args=[app_id, proc.pid]),
        'pid': proc.pid,
        'next': reverse('ca-create-admin', args=[app.id])
    })


@owner_of_app
@confirm_post('Admin erstellen', 'Admin erstellen')
def create_admin(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    password = app.env.juntagrico_database_password

    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(
            [settings.PYTHON_BIN, '-m', 'manage', 'create_admin', app.name, password],
            stdout=out, stderr=out
        )

    render_dict = {
        'title': 'Notiere dieses Passwort: ' + password,
        'step': 'Admin erstellen',
        'pid': proc.pid,
        'next': reverse('overview', args=[app.id])
    }
    return render(request, 'wait_next.html', render_dict)

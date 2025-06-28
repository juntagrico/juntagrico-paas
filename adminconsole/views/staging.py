import subprocess

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from adminconsole.decorators import owner_of_app
from adminconsole.models import App
from adminconsole.util.create_app import make_dirs, git_clone, create_docker_file


@owner_of_app
def create(request, app_id):
    prod_app = App.objects.get(id=app_id)
    if prod_app.stagings.exists():
        return redirect(reverse('overview', args=[prod_app.stagings.first().id]))
    staging_app = App.objects.create(
        name=prod_app.name + '-staging',
        git_clone_url=prod_app.git_clone_url,
        user=request.user,
        port=10000 + prod_app.port,
        staging_of=prod_app,
    )
    return redirect('staging-git-clone', app_id=staging_app.id)


@owner_of_app
def clone_repo(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    errors = []
    success = make_dirs(app.dir, errors)
    if success:
        success &= git_clone(request.user.githubkey.key, app, errors)

    return render(request, 'done_next.html', {
        'errors': '' if success else errors,
        'step': 'Repo Klonen',
        'next': reverse('staging-init-db', args=[app_id]),
    })


@owner_of_app
def init_db(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(
            ['venv/bin/python', '-m', 'manage', 'clone_db', '--no-restart', app.name], stdout=out, stderr=out
        )

    return render(request, 'wait_next.html', {
        'step': 'Datenbank initiieren und kopieren',
        'pid': proc.pid,
        'next': reverse('staging-init-domain', args=[app_id])
    })


@owner_of_app
def init_domain(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    domain = f'{app.name}.juntagrico.science'
    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'add_domain', app.name, str(app.port), domain],
                                stdout=out, stderr=out)

    return render(request, 'wait_next.html', {
        'step': 'Domain einrichten',
        'pid': proc.pid,
        'next': reverse('staging-build-docker', args=[app_id])
    })


@owner_of_app
def rebuild(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(
            ['venv/bin/python', '-m', 'manage', 'rebuild', '--restart', app.name],
            stdout=out, stderr=out
        )

    render_dict = {
        'step': 'docker build and start',
        'pid': proc.pid,
        'next': reverse('show-result', args=[app.id])
    }
    return render(request, 'wait_next.html', render_dict)


@owner_of_app
def restart(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(['venv/bin/python', '-m', 'manage', 'restart', app.name],
                                stdout=out, stderr=out)

    render_dict = {
        'step': 'docker run',
        'pid': proc.pid,
        'next': reverse('show-result', args=[app.id])
    }
    return render(request, 'wait_next.html', render_dict)


@owner_of_app
def clone_db(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(
            ['venv/bin/python', '-m', 'manage', 'clone_db', app.name], stdout=out, stderr=out
        )

    return render(request, 'wait_next.html', {
        'step': 'Datenbank neu erstellen und kopieren',
        'pid': proc.pid,
        'next': reverse('show-result', args=[app.id])
    })


@require_POST
@owner_of_app
def renew(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    create_docker_file(app)

    return redirect('overview', app.id)

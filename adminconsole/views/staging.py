import subprocess

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from adminconsole.decorators import owner_of_app
from adminconsole.models import App
from adminconsole.util.create_app import make_dirs
from adminconsole.util.git import git_clone, git_status


@owner_of_app
def create(request, app_id):
    prod_app = App.objects.get(id=app_id)
    if prod_app.staging_of:
        messages.error(request, f'{prod_app} already is a staging app.')
        return redirect('overview', app_id)
    if prod_app.stagings.exists():
        # resume staging creation process
        return redirect('staging-git-clone', prod_app.stagings.first().id)

    if request.method == 'POST':
        staging_app = App.objects.create(
            name=prod_app.name + '-staging',
            git_clone_url=prod_app.git_clone_url,
            user=request.user,
            port=10000 + prod_app.port,
            staging_of=prod_app,
            version=2,
        )
        return redirect('staging-git-clone', app_id=staging_app.id)

    return render(request, 'generic/submit.html', {
        'page_title': 'Staging einrichten',
        'button_text': f'Staging für {prod_app.name} einrichten',
    })


@owner_of_app
def clone_repo(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    if git_status(app):
        return redirect('staging-init-db', app_id)

    if request.method == 'POST':
        errors = []
        success = make_dirs(app.dir, errors)
        if success:
            success &= git_clone(app, request.user.githubkey.key, errors)

        return render(request, 'generic/done_next_submit.html', {
            'errors': '' if success else errors,
            'step': 'Repo Klonen',
            'next': reverse('staging-init-db', args=[app_id]),
        })

    return render(request, 'generic/submit.html', {
        'page_title': 'Staging Repo Klonen',
        'button_text': 'Repo klonen',
    })


@owner_of_app
def init_db(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    if request.method == 'POST':
        with open(app.log_file, 'wb') as out:
            proc = subprocess.Popen(
                ['venv/bin/python', '-m', 'manage', 'clone_db', '--no-restart', app.name], stdout=out, stderr=out
            )

        return render(request, 'generic/wait_next_submit.html', {
            'step': 'Datenbank initiieren und kopieren',
            'pid': proc.pid,
            'next': reverse('staging-init-domain', args=[app_id])
        })

    return render(request, 'generic/submit.html', {
        'page_title': 'Staging Datenbank erstellen',
        'button_text': 'Datenbank erstellen',
    })


@owner_of_app
def init_domain(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    if request.method == 'POST':
        domain = f'{app.name}.juntagrico.science'
        with open(app.log_file, 'wb') as out:
            proc = subprocess.Popen(
                ['venv/bin/python', '-m', 'manage', 'add_domain', app.name, str(app.port), domain],
                stdout=out, stderr=out
            )

        return render(request, 'generic/wait_next_submit.html', {
            'step': 'Domain einrichten',
            'pid': proc.pid,
            'next': reverse('redeploy-v2', args=[app_id])
        })

    return render(request, 'generic/submit.html', {
        'page_title': 'Domain einrichten',
        'button_text': 'Domain einrichten',
    })


@require_POST
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

    app.renew()

    return redirect('overview', app.id)

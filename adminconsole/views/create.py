import os
import subprocess  # nosec: B404

from cookiecutter.main import cookiecutter
from django.conf import settings

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse

from adminconsole.config import test_localhost
from adminconsole.decorators import owner_of_app
from adminconsole.models import App
from adminconsole.forms import (
    ProjectForm,
    AppForm,
    OverwriteAppForm,
    EnvForm,
    AppEnvVarFormSet,
)
from adminconsole.util import generate_password
from adminconsole.util.admin import ADMIN_USERNAME, PASSWORD_ENV
from adminconsole.util.create_app import find_port
from adminconsole.util.git import git_push_app


@login_required
def app_form(request):
    user = request.user
    if request.method == 'POST':
        app = App(
            user=user,
            port=find_port(),
            creation_pending=True,
            installation_pending=True,
        )
        form = AppForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            return redirect('repo-source', app_id=app.id)
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
            app.creation_pending = False
            app.save()
            return redirect('ca-create-env', app_id=app_id)
    else:
        form = OverwriteAppForm()

    files = os.listdir(app.code_dir)
    if '.git' in files:
        files.remove('.git')

    if not files:
        # if repo is empty, move on with cookiecutter
        return redirect('ca-cookiecutter', app_id=app_id)

    # Otherwise ask what to do
    return render(
        request,
        'create/overwrite.html',
        {
            'form': form,
            'files': files,
        },
    )


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
            if not test_localhost():
                output = []
                success = git_push_app(app, output)
                if not success:
                    return render(
                        request,
                        'generic/error.html',
                        {
                            'step': 'Cookiecutter anwenden und repo pushen',
                            'errors': [output],
                        },
                    )
            app.creation_pending = False
            app.save()
            return redirect('ca-create-env', app_id=app_id)
    else:
        form = ProjectForm(initial={'project_slug': app.name})

    return render(request, 'create/ck.html', {'form': form})


@owner_of_app
def env_form(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    if request.method == 'POST':
        form = EnvForm(request.POST, instance=app.env)
        formset = AppEnvVarFormSet(request.POST, instance=app.env)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            # Generate admin password and pass it safely via environment variable
            password = generate_password()
            # reset installation_pending flag if setup is repeated
            app.installation_pending = True
            app.save()
            with open(app.log_file, 'wb') as out:
                proc = subprocess.Popen(  # nosec: B603
                    [settings.PYTHON_BIN, '-m', 'manage', 'setup', app.name],
                    stdout=out,
                    stderr=out,
                    env={**os.environ, PASSWORD_ENV: password},
                )
            return render(
                request,
                'flow/setup_result.html',
                {
                    'step': 'App einrichten',
                    'page_title': 'App einrichten',
                    'url': reverse('progress', args=[app_id, proc.pid]),
                    'pid': proc.pid,
                    'next': reverse('overview', args=[app.id]),
                    'admin_username': ADMIN_USERNAME,
                    'admin_password': password,
                    'show_result_url': reverse('show-result', args=[app.id])
                    + '?from_setup=1',
                },
            )
    else:
        form = EnvForm(instance=app.env)
        formset = AppEnvVarFormSet(instance=app.env)
    return render(
        request,
        'app/env.html',
        {'form': form, 'formset': formset, 'app': app, 'is_setup': True},
    )

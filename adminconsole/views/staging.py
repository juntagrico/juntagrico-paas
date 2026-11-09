import subprocess  # nosec: B404

from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from adminconsole.decorators import owner_of_app
from adminconsole.models import App
from adminconsole.util import parse_log_file
from adminconsole.views.generic import audit_log, client_address


@owner_of_app
def create(request, app_id):
    prod_app = App.objects.get(id=app_id)
    if prod_app.staging_of:
        messages.error(request, f'{prod_app} already is a staging app.')
        return redirect('overview', app_id)
    existing = prod_app.stagings.first()
    if existing and not existing.installation_pending:
        # Staging already installed, no action needed
        messages.info(request, f'Staging für {prod_app.name} existiert bereits.')
        return redirect('overview', existing.id)

    if request.method == 'POST':
        audit_log.info(
            '%s creates staging for %s from %s',
            request.user,
            prod_app.name,
            client_address(request),
        )
        if existing and existing.installation_pending:
            # Staging exists but installation failed or is pending, reuse it
            # Reset properties in case production app changed since the last attempt
            existing.name = prod_app.name + '-staging'
            existing.git_clone_url = prod_app.git_clone_url
            existing.git_branch = prod_app.git_branch
            existing.port = 10000 + prod_app.port
            existing.wsgi = prod_app.wsgi
            existing.installation_pending = True
            existing.save()
            staging_app = existing
        else:
            staging_app = App.objects.create(
                name=prod_app.name + '-staging',
                git_clone_url=prod_app.git_clone_url,
                git_branch=prod_app.git_branch,
                user=request.user,
                port=10000 + prod_app.port,
                wsgi=prod_app.wsgi,
                staging_of=prod_app,
                version=2,
                installation_pending=True,
            )
        # Spawn setup_staging as a background task
        with open(staging_app.log_file, 'wb') as out:
            proc = subprocess.Popen(  # nosec: B603
                [
                    settings.PYTHON_BIN,
                    '-m',
                    'manage',
                    'setup_staging',
                    staging_app.name,
                ],
                stdout=out,
                stderr=out,
            )

        app_id = staging_app.id
        progress_url = reverse('progress', args=[app_id, proc.pid])

        return render(
            None,  # request not needed for this template
            'flow/wait_redeploy.html',
            {
                'page_title': f'Staging für {prod_app.name} einrichten',
                'step': 'Staging einrichten',
                'url': progress_url,
                'pid': proc.pid,
                'next': reverse('staging-result', args=[app_id]),
            },
        )

    return render(
        request,
        'generic/submit.html',
        {
            'page_title': 'Staging einrichten',
            'button_text': f'Staging für {prod_app.name} einrichten',
        },
    )


@require_POST
@owner_of_app
def clone_db(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    audit_log.info(
        '%s clones database of %s from %s',
        request.user,
        app.name,
        client_address(request),
    )
    with open(app.log_file, 'wb') as out:
        proc = subprocess.Popen(  # nosec: B603
            [settings.PYTHON_BIN, '-m', 'manage', 'clone_db', app.name],
            stdout=out,
            stderr=out,
        )

    return render(
        request,
        'flow/wait_next.html',
        {
            'step': 'Datenbank neu erstellen und kopieren',
            'pid': proc.pid,
            'next': reverse('show-result', args=[app.id]),
        },
    )


@require_POST
@owner_of_app
def renew(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    audit_log.info(
        '%s renews staging %s from %s',
        request.user,
        app.name,
        client_address(request),
    )
    app.renew()

    return redirect('overview', app.id)


@owner_of_app
def result(request, app_id):
    """Show the setup result for a staging app with a retry button on failure."""
    app = get_object_or_404(App, pk=app_id)
    sections = parse_log_file(app)
    context = {'app': app, 'sections': sections}
    return render(request, 'staging/result.html', context)

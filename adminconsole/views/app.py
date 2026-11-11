import ast
import json
import subprocess  # nosec: B404
from collections import OrderedDict
from django.utils import timezone

import docker
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from docker.errors import APIError, DockerException, NotFound
from django_otp import user_has_device

from adminconsole.decorators import owner_of_app
from adminconsole.forms import EnvForm, BranchForm, AppEnvVarFormSet
from adminconsole.models import App
from adminconsole.util import generate_password, parse_log_file, _mask_value
from adminconsole.util.admin import ADMIN_USERNAME, set_admin_password_in_container
from adminconsole.util.docker import create_container, exec_run, stop_container
from adminconsole.util.git import git_switch, git_current_branch
from adminconsole.util.log_parsing import parse_log_line, format_timestamp
from adminconsole.views.generic import (
    confirm_post,
    confirm_password,
    audit_log,
    client_address,
)


@require_POST
@owner_of_app
def start(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    audit_log.info(
        '%s starts %s from %s', request.user, app.name, client_address(request)
    )
    if app.staging_of:
        app.renew()

    try:
        create_container(app)
    except (DockerException, APIError) as e:
        messages.error(request, str(e))
        return redirect('overview', app.id)

    return redirect('overview', app.id)


@require_POST
@owner_of_app
def stop(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    audit_log.info(
        '%s stops %s from %s', request.user, app.name, client_address(request)
    )
    try:
        stop_container(app.name)
    except (DockerException, APIError) as e:
        messages.error(request, str(e))

    return redirect('overview', app.id)


@staff_member_required
@confirm_post('Admin-Passwort neu setzen', 'Neues Passwort setzen')
@never_cache
def reset_admin_password(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    audit_log.info(
        '%s resets admin password of %s from %s',
        request.user,
        app.name,
        client_address(request),
    )
    password = generate_password()
    exit_code = set_admin_password_in_container(app, password)
    if exit_code != 0:
        messages.error(
            request,
            f'Das Passwort konnte nicht gesetzt werden. Gibt es den Benutzer «{ADMIN_USERNAME}»?',
        )
        return redirect('overview', app.id)

    # shown once and never stored, also not in messages, which may end up in a cookie
    return render(
        request,
        'app/admin_password.html',
        {'app': app, 'username': ADMIN_USERNAME, 'password': password},
    )


@owner_of_app
def overview(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    # Redirect to repo selection if creation hasn't been completed
    if app.creation_pending:
        return redirect('repo-source', app_id=app.id)

    staging = app.staging_of is not None

    # Redirect if installation is still pending
    if app.installation_pending:
        if staging:
            return redirect('staging-create', app_id=app.staging_of.id)
        return redirect('ca-create-env', app_id=app.id)

    running = app.running

    # Get staging app running status if this is the main app
    staging_running = None
    if not staging and app.stagings.exists():
        staging_app = app.stagings.first()
        staging_running = staging_app.running

    renderdict = {
        'app': app,
        'running': running,
        'staging': staging,
        'staging_running': staging_running,
        'has_2fa': user_has_device(request.user),
    }
    return render(request, 'app/overview.html', renderdict)


@owner_of_app
def show_result(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    sections = parse_log_file(app)

    return render(
        request,
        'flow/show_result.html',
        {'app': app, 'sections': sections},
    )


@owner_of_app
def env(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    app_env = app.env

    if request.method == 'POST':
        form = EnvForm(request.POST, instance=app_env)
        formset = AppEnvVarFormSet(request.POST, instance=app_env)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            audit_log.info(
                '%s updates settings of %s from %s',
                request.user,
                app.name,
                client_address(request),
            )
            # Only restart the container if it currently exists
            container_exists = False
            try:
                docker.from_env().containers.get(app.name)
                container_exists = True
            except NotFound:
                pass
            if container_exists:
                with open(app.log_file, 'wb') as out:
                    proc = subprocess.Popen(  # nosec: B603
                        [settings.PYTHON_BIN, '-m', 'manage', 'restart', app.name],
                        stdout=out,
                        stderr=out,
                    )
                return render(
                    request,
                    'flow/wait_next.html',
                    {
                        'step': 'Einstellungen anwenden',
                        'pid': proc.pid,
                        'next': reverse('overview', args=[app.id]),
                    },
                )
            else:
                messages.info(
                    request,
                    'Einstellungen gespeichert. Die Instanz ist inaktiv; die Änderungen werden beim nächsten Start wirksam.',
                )
                return redirect('overview', app.id)
    else:
        form = EnvForm(instance=app_env)
        formset = AppEnvVarFormSet(instance=app_env)

    # Extract SMTP error message for display in the email section
    smtp_error = None
    if form.has_error('__all__', 'smtp_error'):
        smtp_error = form.errors['__all__'][0]

    return render(
        request,
        'app/env.html',
        {'form': form, 'formset': formset, 'app': app, 'smtp_error': smtp_error},
    )


@owner_of_app
def show_env(request, app_id):
    """Display current Django settings by running diffsettings in the container, hiding sensitive values."""
    app = get_object_or_404(App, pk=app_id)

    # Collect values from secret AppEnvVars so we can mask settings that match them
    secret_values = set(
        app.env.env_vars.filter(secret=True)
        .exclude(value='')
        .values_list('value', flat=True)
    )
    secret_values |= {
        app.env.juntagrico_secret_key,
        app.env.juntagrico_database_password,
        app.env.juntagrico_email_password,
    }
    secret_values.discard('')

    # Run diffsettings inside the container to get the actual Django settings
    try:
        container = app.container
        result = container.exec_run(
            ['python', '-m', 'manage', 'diffsettings'], stderr=False
        )
        output = result.output.decode('utf-8')
    except DockerException as e:
        messages.error(request, f'Container nicht erreichbar: {e}')
        output = ''

    # Parse the diffsettings output
    # Format: "SETTING_NAME = value" or "SETTING_NAME = value ###"
    # The ### marker means the setting is not in Django defaults
    settings_entries = []
    if output.strip():
        # First pass: build a raw dict of {key: value}
        raw_settings = {}
        for line in output.strip().splitlines():
            line = line.strip()
            if not line or line.startswith('---') or line.startswith('+++'):
                continue
            line = line.replace('###', '').strip()
            if '=' in line:
                key, _, value_str = line.partition('=')
                key = key.strip()
                value_str = value_str.strip()
                # Try to parse as a Python literal; fall back to the raw string
                try:
                    raw_settings[key] = ast.literal_eval(value_str)
                except (ValueError, SyntaxError, TypeError):
                    raw_settings[key] = value_str
        # Second pass: mask sensitive keys and secret values recursively
        masked_settings = _mask_value(raw_settings, secret_values)
        for key, value in masked_settings.items():
            settings_entries.append({
                'key': key,
                'value': value,
            })

    return render(
        request,
        'app/show_env.html',
        {
            'settings': settings_entries,
            'app': app,
        },
    )


@owner_of_app
def change_branch(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    error = ''
    success = False
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            error = git_switch(app, form.cleaned_data['branch'])
            success = not error
            audit_log.info(
                '%s changes branch of %s to %s from %s',
                request.user,
                app.name,
                form.cleaned_data['branch'],
                client_address(request),
            )

    form = BranchForm(initial={'branch': git_current_branch(app)})
    return render(
        request,
        'app/branch_form.html',
        {'form': form, 'success': success, 'error': error, 'app': app},
    )


@owner_of_app
@confirm_post('Depotliste generieren', 'Depotliste erzeugen')
def generate_depot_list(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    audit_log.info(
        '%s generates depot list of %s from %s',
        request.user,
        app.name,
        client_address(request),
    )
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'generate_depot_list', '--force']
    container.exec_run(cmd)
    render_dict = {
        'step': 'Depotliste generieren',
        'next': reverse('overview', args=[app.id]),
    }
    return render(request, 'flow/done_next.html', render_dict)


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
    # parse output
    sections = {'Log': {'text': '', 'result': 1}}
    current = sections['Log']  # capture error output before the first section
    for line in result_text.split('\n'):
        line = line.strip()
        if line.startswith('*** '):
            line = line.strip(' *')
            if line not in sections:
                sections[line] = {'text': '', 'result': 0}
            current = sections[line]
        else:
            current['text'] += line + '\n'
    if not sections['Log']['text']:
        del sections['Log']
    return render(
        request,
        'flow/show_result.html',
        {'app': app, 'sections': sections, 'title': 'Email-Texte'},
    )


def _stream_dumpdata(container, cmd):
    """Stream dumpdata output from a Docker container in real-time."""
    result = exec_run(container, cmd, stderr=False, stream=True)
    for chunk in result.output:
        yield chunk


@owner_of_app
@confirm_password('Daten exportieren (JSON)', 'Exportieren')
def dumpdata(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    audit_log.info(
        '%s exports JSON of %s from %s', request.user, name, client_address(request)
    )
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = [
        'python',
        '-m',
        'manage',
        'dumpdata',
        '--natural-foreign',
        '--natural-primary',
        '-e',
        'sessions',
    ]
    response = StreamingHttpResponse(
        _stream_dumpdata(container, cmd), content_type='application/json'
    )
    response['Content-Disposition'] = (
        f'attachment; filename={name}-{timezone.now().strftime("%y_%m_%d_%H_%M")}.json'
    )
    return response


def _stream_pgdump(app):
    """Stream pg_dump output in real-time."""
    db_user = settings.DATABASES['default']['USER']
    db_pw = settings.DATABASES['default']['PASSWORD']

    proc = subprocess.Popen(  # nosec: B603, B607
        ['pg_dump', '-U', db_user, '--no-password', app.env.juntagrico_database_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={'PGPASSWORD': db_pw},
    )
    try:
        for chunk in iter(lambda: proc.stdout.read(65536), b''):
            yield chunk
    finally:
        proc.stdout.close()
        proc.wait()


@owner_of_app
@confirm_password('Daten exportieren (SQL)', 'Exportieren')
def pgdump(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    audit_log.info(
        '%s exports SQL of %s from %s', request.user, name, client_address(request)
    )
    response = StreamingHttpResponse(
        _stream_pgdump(app), content_type='application/sql'
    )
    response['Content-Disposition'] = (
        f'attachment; filename={name}-{timezone.now().strftime("%y_%m_%d_%H_%M")}.sql'
    )
    return response


@owner_of_app
def logs(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    result_text = container.logs(tail=1000, timestamps=True)
    result_text = result_text.decode('utf-8')

    # Parse raw log text into structured entries
    raw_lines = result_text.split('\n')
    entries = []
    for line in raw_lines:
        parsed = parse_log_line(line)
        if parsed is not None:
            entries.append(parsed)

    # Collect unique levels for filter buttons
    levels = sorted(set(e['level'] for e in entries))

    # Format timestamps for display
    for entry in entries:
        entry['timestamp_display'] = format_timestamp(entry['timestamp'])

    return render(
        request,
        'app/logs.html',
        {
            'app': app,
            'log_entries': entries,
            'levels': levels,
        },
    )


@require_POST
@owner_of_app
def create_cache_table(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    audit_log.info(
        '%s creates cache table for %s from %s',
        request.user,
        app.name,
        client_address(request),
    )
    try:
        container = docker.from_env().containers.get(app.name)
    except NotFound:
        messages.error(request, 'Die Instanz ist nicht aktiv.')
        return redirect('overview', app_id)
    result = container.exec_run(['python', '-m', 'manage', 'createcachetable'])
    if result.exit_code == 0:
        messages.success(request, 'Cache-Tabelle wurde erstellt.')
    else:
        messages.error(
            request,
            f'Fehler beim Erstellen der Cache-Tabelle: {result.output.decode()[-200:]}',
        )
    return redirect('overview', app_id)


@owner_of_app
def versions(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)

    python_version = None
    pip_version = None
    packages = []
    errors = []

    # Batch all version lookups into a single exec_run call to minimize Docker API overhead.
    # The Python script collects Python version and all package metadata, then outputs
    # a single JSON object.
    try:
        result = container.exec_run(
            [
                'python',
                '-c',
                """
import importlib.metadata, json, sys

data = {"python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", "packages": []}
for d in importlib.metadata.distributions():
    name = d.metadata["Name"]
    if name and d.version:
        data["packages"].append([name, d.version])

print(json.dumps(data))
""",
            ],
            stderr=False,
        )
        output = result.output.decode('utf-8').strip()
        if result.exit_code == 0 and output:
            data = json.loads(output)
            python_version = data.get('python_version')
            for pkg_name, version in data.get('packages', []):
                if pkg_name.lower() == 'pip':
                    pip_version = version
                else:
                    packages.append({'name': pkg_name, 'version': version})
    except Exception as e:
        errors.append(f'Versionsabfrage: {e}')

    # Categorize packages by prefix into titled groups
    PACKAGE_CATEGORIES = [
        ('juntagrico', 'juntagrico'),
        ('django', 'Django'),
        ('gunicorn', 'gunicorn'),
        ('psycopg', 'psycopg'),
    ]

    categories = OrderedDict()
    for _, title in PACKAGE_CATEGORIES:
        categories[title] = []
    categories['Andere Pakete'] = []

    for pkg in packages:
        name_lower = pkg['name'].lower()
        matched = False
        for prefix, title in PACKAGE_CATEGORIES:
            if name_lower.startswith(prefix):
                categories[title].append(pkg)
                matched = True
                break
        if not matched:
            categories['Andere Pakete'].append(pkg)

    # Sort each group by name and remove empty categories
    packages_dict = {
        title: sorted(pkgs, key=lambda p: p['name'].lower())
        for title, pkgs in categories.items()
        if pkgs
    }

    return render(
        request,
        'app/versions.html',
        {
            'app': app,
            'python_version': python_version,
            'pip_version': pip_version,
            'packages': packages_dict,
            'errors': errors,
        },
    )

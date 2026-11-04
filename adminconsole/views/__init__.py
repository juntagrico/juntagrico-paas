import ast
import json
import re
import subprocess
from collections import OrderedDict, defaultdict

import docker
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django_otp import user_has_device
from docker.errors import DockerException, NotFound

from adminconsole.decorators import owner_of_app
from adminconsole.forms import EnvForm, ProfileForm, BranchForm, AppEnvVarFormSet
from adminconsole.models import App
from adminconsole.util import pid_finished
from adminconsole.util.docker import get_container_statuses
from adminconsole.util.git import git_switch, git_current_branch
from adminconsole.util.log_summary import build_summary
from adminconsole.views.generic import confirm_post, confirm_password, security_log, client_address


@login_required
def home(request):
    superuser = request.user.is_superuser
    if superuser:
        available_apps = App.objects.filter(staging_of__isnull=True).order_by('name')
    else:
        available_apps = request.user.app.filter(staging_of__isnull=True).order_by('name')
    number_of_apps = available_apps.count()
    if number_of_apps == 1 and not superuser:
        return redirect('overview', app_id=available_apps[0].id)

    # Get all container statuses in a single Docker API call (include staging apps)
    if superuser:
        app_names = set(App.objects.values_list('name', flat=True))
    else:
        app_names = set(request.user.app.values_list('name', flat=True))
    container_statuses = get_container_statuses(app_names)

    # Group apps by their first letter
    grouped_apps = defaultdict(list)
    for app in available_apps:
        first_letter = app.name[0].upper() if app.name else '#'
        grouped_apps[first_letter].append(app)

    return render(request, 'home.html', {
        'grouped_apps': dict(sorted(grouped_apps.items())),
        'number_of_apps': number_of_apps,
        'can_add_app': number_of_apps < 1 or superuser,
        'container_statuses': container_statuses,
    })


@owner_of_app
def overview(request, app_id):
    app = get_object_or_404(App, pk=app_id)

    running = app.running

    staging = app.staging_of is not None
    if staging and not app.code_dir.is_dir():
        # resume staging creation process
        return redirect('staging-git-clone', app_id=app.id)

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
    return render(request, 'overview.html', renderdict)


@login_required
def pidcheck(request, pid):
    return JsonResponse({
        'finished': pid_finished(pid)
    })


@owner_of_app
def show_result(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    # parse log
    sections = {'Log': {'text': '', 'result': 1}}
    current = sections['Log']  # capture error output before the first section
    with open(app.log_file, 'r') as file:
        while line := file.readline():
            line = line.strip()
            if line.startswith('# '):
                line = line[2:]
                if line not in sections:
                    sections[line] = {'text': '', 'result': 1}
                current = sections[line]
            elif line.startswith('Return '):
                try:
                    current['result'] = int(line[7:])
                except ValueError:
                    pass
            else:
                if line[:2] in ['b"', "b'"]:
                    current['text'] += str(ast.literal_eval(line), 'utf-8')
                else:
                    current['text'] += line
                current['text'] += '\n'
    if not sections['Log']['text']:
        del sections['Log']

    # Build summaries for each section
    for section_name, section in sections.items():
        section['summary'] = build_summary(section['text'], section['result'], section_name)

    return render(request, 'app/show_result.html',
                  {'app': app, 'sections': sections})


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
            # Only restart the container if it currently exists
            container_exists = False
            try:
                docker.from_env().containers.get(app.name)
                container_exists = True
            except NotFound:
                pass
            if container_exists:
                with open(app.log_file, 'wb') as out:
                    proc = subprocess.Popen(
                        [settings.PYTHON_BIN, '-m', 'manage', 'restart', app.name],
                        stdout=out, stderr=out
                    )
                return render(request, 'app/wait_next.html', {
                    'step': 'Einstellungen anwenden',
                    'pid': proc.pid,
                    'next': reverse('overview', args=[app.id])
                })
            else:
                messages.info(request, 'Einstellungen gespeichert. Die Instanz ist inaktiv; die Änderungen werden beim nächsten Start wirksam.')
                return redirect('overview', app.id)
    else:
        form = EnvForm(instance=app_env)
        formset = AppEnvVarFormSet(instance=app_env)

    # Extract SMTP error message for display in the email section
    smtp_error = None
    if form.has_error('__all__', 'smtp_error'):
        smtp_error = form.errors['__all__'][0]

    return render(request, 'app/env.html', {'form': form, 'formset': formset, 'app': app, 'smtp_error': smtp_error})


def _is_sensitive_key(key):
    """Check if a key name contains sensitive patterns."""
    sensitive_patterns = {'SECRET', 'PASSWORD'}
    return any(pattern in str(key).upper() for pattern in sensitive_patterns)


def _mask_value(value, secret_values=None):
    """Return a masked representation of a value, recursively handling nested structures.
    
    Args:
        value: The value to mask.
        secret_values: A set of string values that should be masked if found as substrings.
    """
    if secret_values is None:
        secret_values = set()
    if isinstance(value, dict):
        masked = {}
        for k, v in value.items():
            if _is_sensitive_key(k):
                masked[k] = '****'
            else:
                masked[k] = _mask_value(v, secret_values)
        return masked
    elif isinstance(value, (list, tuple)):
        masked = [_mask_value(item, secret_values) for item in value]
        return type(value)(masked)
    elif isinstance(value, str):
        masked = value
        for secret in secret_values:
            masked = masked.replace(secret, '****')
        return masked
    else:
        return value


@owner_of_app
def show_env(request, app_id):
    """Display current Django settings by running diffsettings in the container, hiding sensitive values."""
    app = get_object_or_404(App, pk=app_id)

    # Patterns that mark a setting key as sensitive
    sensitive_key_patterns = {'SECRET', 'PASSWORD'}

    # Collect values from secret AppEnvVars so we can mask settings that match them
    secret_values = set(app.env.env_vars.filter(secret=True).exclude(value='').values_list('value', flat=True))
    secret_values.add(app.env.juntagrico_secret_key)
    secret_values.add(app.env.juntagrico_database_password)
    secret_values.add(app.env.juntagrico_email_password)

    # Run diffsettings inside the container to get the actual Django settings
    try:
        container = app.container
        result = container.exec_run(['python', '-m', 'manage', 'diffsettings'], stderr=False)
        output = result.output.decode('utf-8')
    except DockerException as e:
        messages.error(request, f'Container nicht erreichbar: {e}')
        output = ''

    # Parse the diffsettings output
    # Format: "SETTING_NAME = value" or "SETTING_NAME = value ###"
    # The ### marker means the setting is not in Django defaults
    settings_entries = []
    if output.strip():
        for line in output.strip().splitlines():
            line = line.strip()
            if not line or line.startswith('---') or line.startswith('+++'):
                # Skip diff separators in unified format
                continue
            # Remove the ### marker if present (indicates setting not in Django defaults)
            is_custom = '###' in line
            line = line.replace('###', '').strip()
            # Parse "SETTING_NAME = value"
            if '=' in line:
                key, _, value_str = line.partition('=')
                key = key.strip()
                value_str = value_str.strip()
                is_sensitive = any(pattern in key.upper() for pattern in sensitive_key_patterns)
                # Also mask if the value contains a secret AppEnvVar value as a substring
                if not is_sensitive:
                    for secret in secret_values:
                        if secret in value_str:
                            is_sensitive = True
                            break
                # Try to parse the value as a Python literal (dict, list, tuple, etc.)
                parsed_value = None
                value_type = 'string'
                if not is_sensitive:
                    try:
                        parsed = ast.literal_eval(value_str)
                        if isinstance(parsed, (dict, list, tuple)):
                            # Recursively mask sensitive keys and secret values within nested structures
                            parsed_value = _mask_value(parsed, secret_values)
                            value_type = type(parsed).__name__
                    except (ValueError, SyntaxError, TypeError):
                        pass
                settings_entries.append({
                    'key': key,
                    'value': value_str if not is_sensitive else '****',
                    'parsed_value': parsed_value,
                    'value_type': value_type,
                    'hidden': is_sensitive,
                    'custom': is_custom,
                })

    return render(request, 'app/show_env.html', {
        'settings': settings_entries,
        'app': app,
    })


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

    form = BranchForm(initial={'branch': git_current_branch(app)})
    return render(request, 'app/branch_form.html', {
        'form': form, 'success': success, 'error': error, 'app': app
    })


@owner_of_app
@confirm_post('Depotliste generieren', 'Depotliste erzeugen')
def generate_depot_list(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'generate_depot_list', '--force']
    container.exec_run(cmd)
    render_dict = {
        'step': 'Depotliste generieren',
        'next': reverse('overview', args=[app.id])
    }
    return render(request, 'app/done_next.html', render_dict)


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
        'app/show_result.html',
        {'app': app, 'sections': sections, 'title': 'Email-Texte'},
    )


@owner_of_app
@confirm_password('Daten exportieren (JSON)', 'Exportieren')
def dumpdata(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    security_log.info('%s exports JSON of %s from %s', request.user, name, client_address(request))
    client = docker.from_env()
    container = client.containers.get(name)
    cmd = ['python', '-m', 'manage', 'dumpdata', '--natural-foreign', '--natural-primary', '-e', 'sessions']
    result = container.exec_run(cmd, stderr=False)
    response = HttpResponse(result.output.decode('utf-8'), content_type="application/json")
    response['Content-Disposition'] = f'attachment; filename={name}-{timezone.now().strftime("%y_%m_%d_%H_%M")}.json'
    return response


@owner_of_app
@confirm_password('Daten exportieren (SQL)', 'Exportieren')
def pgdump(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    security_log.info('%s exports SQL of %s from %s', request.user, app.name, client_address(request))
    db_user = settings.DATABASES['default']['USER']
    db_pw = settings.DATABASES['default']['PASSWORD']

    dump = subprocess.run(
        ['pg_dump', '-U', db_user, '--no-password', app.env.juntagrico_database_name],
        stdout=subprocess.PIPE, env={'PGPASSWORD': db_pw}
    )
    response = HttpResponse(dump.stdout.decode('utf-8'), content_type="application/sql")
    response['Content-Disposition'] = f'attachment; filename={app.name}-{timezone.now().strftime("%y_%m_%d_%H_%M")}.sql'
    return response


# Regex patterns for log line parsing
# Gunicorn: [2026-11-03 08:51:05 +0000] [1] [INFO] Starting gunicorn 25.1.0
# Django: [2026-11-03 10:07:37,854] WARNING Not Found: //wp-includes/wlwmanifest.xml
# Stack trace lines: indented or continuation lines
# Timestamp-only lines: 2026-11-03 12:47:37.895945+01:00 (health checks, log flushes, keep-alives)
LOG_LINE_RE = re.compile(
    r'^\[(?P<timestamp>[^\]]+)\]\s+'
    r'(?:\[(?P<pid>\d+)\]\s+)?'
    r'(?:\[(?P<level>INFO|WARNING|ERROR|CRITICAL|DEBUG)\]\s+)?'
    r'(?P<message>.*)',
    re.IGNORECASE
)

DJANGO_LOG_RE = re.compile(
    r'^\[(?P<timestamp>[^\]]+)\]\s+'
    r'(?P<level>INFO|WARNING|ERROR|CRITICAL|DEBUG)\s+'
    r'(?P<message>.*)',
    re.IGNORECASE
)

# Timestamp-only lines (ISO 8601 with microseconds and timezone offset)
# e.g. 2026-11-03 12:47:37.895945+01:00
TIMESTAMP_ONLY_RE = re.compile(
    r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2}$'
)

# Date and time extraction for display
# Matches YYYY-MM-DD HH:MM:SS from various timestamp formats
DATETIME_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{2}:\d{2}:\d{2})')

MONTH_ABBR = {
    '01': 'Jan', '02': 'Feb', '03': 'Mär', '04': 'Apr',
    '05': 'Mai', '06': 'Jun', '07': 'Jul', '08': 'Aug',
    '09': 'Sep', '10': 'Okt', '11': 'Nov', '12': 'Dez'
}


def format_timestamp(raw):
    """Format a raw timestamp string for compact display.
    Returns a shortened version showing date and time, e.g. '03 Nov 08:51:05'.
    """
    if not raw:
        return ''
    match = DATETIME_RE.search(raw)
    if match:
        year, month, day, time = match.groups()
        month_str = MONTH_ABBR.get(month, month)
        # Strip trailing zeros from day for compactness
        day_int = int(day)
        return f'{day_int} {month_str} {time}'
    # Fallback: return raw
    return raw


def parse_log_line(line):
    """Parse a single log line into structured data.
    Returns a dict with timestamp, level, pid, message, and is_continuation fields.
    """
    line = line.rstrip('\r\n')
    if not line:
        return None

    # Try Gunicorn format first
    match = LOG_LINE_RE.match(line)
    if match and (match.group('level') or match.group('pid')):
        level = match.group('level')
        return {
            'timestamp': match.group('timestamp') or '',
            'level': level.upper() if level else 'UNKNOWN',
            'pid': match.group('pid') or '',
            'message': match.group('message') or '',
            'is_continuation': False,
        }

    # Try Django format
    match = DJANGO_LOG_RE.match(line)
    if match:
        return {
            'timestamp': match.group('timestamp') or '',
            'level': (match.group('level') or 'INFO').upper(),
            'pid': '',
            'message': match.group('message') or '',
            'is_continuation': False,
        }

    # Check if it's a stack trace / continuation line (starts with whitespace or traceback pattern)
    if line.startswith((' ', '\t', 'Traceback', 'File "', '  ')):
        return {
            'timestamp': '',
            'level': 'TRACE',
            'pid': '',
            'message': line,
            'is_continuation': True,
        }

    # Check if it's a timestamp-only line (health check, log flush, keep-alive)
    if TIMESTAMP_ONLY_RE.match(line):
        return {
            'timestamp': line,
            'level': 'HEARTBEAT',
            'pid': '',
            'message': '',
            'is_continuation': False,
        }

    # Fallback: treat as unknown level
    return {
        'timestamp': '',
        'level': 'UNKNOWN',
        'pid': '',
        'message': line,
        'is_continuation': False,
    }


@owner_of_app
def logs(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    name = app.name
    client = docker.from_env()
    container = client.containers.get(name)
    result_text = container.logs(tail=1000)
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

    return render(request, 'app/logs.html', {
        'app': app,
        'log_entries': entries,
        'levels': levels,
    })


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

    # Get Python version (python --version writes to stderr, so merge streams)
    try:
        result = container.exec_run(['python', '--version'], stderr=True)
        output = result.output.decode('utf-8').strip()
        if output:
            # "Python 3.11.18" -> "3.11.18"
            match = re.search(r'Python\s+(\S+)', output)
            if match:
                python_version = match.group(1)
            else:
                python_version = output
    except Exception as e:
        errors.append(f'Python-Version: {e}')

    # Get pip version
    try:
        result = container.exec_run(['pip', '--version'])
        output = result.output.decode('utf-8').strip()
        if result.exit_code == 0 or output:
            # "pip 26.2.2 from /usr/local/lib/python3.11/site-packages/pip (python 3.11)"
            match = re.search(r'pip\s+(\S+)', output)
            if match:
                pip_version = match.group(1)
            elif output:
                pip_version = output
    except Exception as e:
        errors.append(f'pip-Version: {e}')

    # Get installed packages using JSON format for reliable parsing
    try:
        result = container.exec_run(
            ['pip', 'list', '--format', 'json', '--disable-pip-version-check'],
            stderr=False,
        )
        output = result.output.decode('utf-8').strip()
        if output:
            parsed = json.loads(output)
            for pkg in parsed:
                pkg_name = pkg.get('name', 'unknown')
                version = pkg.get('version', 'unknown')
                if pkg_name and version:
                    packages.append({'name': pkg_name, 'version': version})
    except Exception as e:
        errors.append(f'Paketliste: {e}')

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



@login_required
def profile(request):
    user = request.user
    if request.method == 'POST':
        form = ProfileForm(request.POST)
        if form.is_valid():
            user.email = form.cleaned_data.get('email')
            user.save()
            return redirect('/')
    else:
        form = ProfileForm({'email': user.email})
    return render(request, 'profile.html', {'form': form})

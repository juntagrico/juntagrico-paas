from io import StringIO

import docker
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.management import call_command
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render, redirect

from adminconsole.decorators import owner_of_app
from adminconsole.models import App
from adminconsole.views.generic import audit_log, client_address


@owner_of_app
def update_permissions(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    cmd = ['python', '-m', 'manage', 'update_permissions']
    container = docker.from_env().containers.get(app.name)
    if request.method == 'POST':
        audit_log.info(
            '%s updates permissions of %s from %s',
            request.user,
            app.name,
            client_address(request),
        )
        result = container.exec_run(cmd)
        messages.success(request, result[1].decode().split('\n')[-2])
        return redirect('overview', app_id)

    cmd += ['--dry']
    result = container.exec_run(cmd)
    delete_perms = []
    rename_perms = []
    if result[0] == 0:
        for line in result[1].decode().split('\n'):
            if line.startswith('Delete permission: '):
                delete_perms.append(line[len('Delete permission: ') :])
            if line.startswith('Rename permission: '):
                rename_perms.append(line[len('Rename permission: ') :])

    return render(
        request,
        'app/update_permissions.html',
        {
            'app': app,
            'delete_perms': delete_perms,
            'rename_perms': rename_perms,
            'error': result[0],
        },
    )


@owner_of_app
def sanitize_richtext(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    cmd = ['python', '-m', 'manage', 'sanitize_richtext', '--dry-run']
    container = docker.from_env().containers.get(app.name)
    if request.method == 'POST':
        result = container.exec_run(cmd[:-1])
        messages.success(request, result[1].decode().strip())
        return redirect('overview', app_id)

    result = container.exec_run(cmd)
    sanitized = []
    if result[0] == 0:
        for line in result[1].decode().split('\n'):
            # Expected format: "app.Model.field: N record(s) would update."
            line = line.strip()
            if ': ' in line and 'record(s) would update' in line:
                field_name, count_text = line.split(': ')
                count = count_text.split(' ')[0]
                if count != '0':
                    sanitized.append((field_name, count))

    return render(
        request,
        'tools/sanitize_richtext.html',
        {
            'app': app,
            'sanitized': sanitized,
            'error': result[0],
        },
    )


@user_passes_test(lambda u: u.is_superuser)
def reload_versions(request):
    app_name = request.GET.get('app')
    package = request.GET.get('package')
    out = StringIO()
    call_command('collect_version', app_name=app_name, package=package, stdout=out)
    return HttpResponse('OK\n' + out.getvalue())

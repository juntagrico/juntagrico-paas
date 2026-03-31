import docker
from django.contrib import messages
from django.shortcuts import get_object_or_404, render, redirect

from adminconsole.decorators import owner_of_app
from adminconsole.models import App


@owner_of_app
def update_permissions(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    cmd = ['python', '-m', 'manage', 'update_permissions']
    container = docker.from_env().containers.get(app.name)
    if request.method == 'POST':
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
                delete_perms.append(line[len('Delete permission: '):])
            if line.startswith('Rename permission: '):
                rename_perms.append(line[len('Rename permission: '):])

    return render(request, 'tools/update_permissions.html', {
        'app': app,
        'delete_perms': delete_perms,
        'rename_perms': rename_perms,
        'error': result[0],
    })

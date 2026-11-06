import subprocess

from django.conf import settings
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from adminconsole.decorators import owner_of_app
from adminconsole.forms import CronjobForm
from adminconsole.models import App


@owner_of_app
def manage(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    if request.method == 'POST':
        form = CronjobForm(request.POST, app=app)
        if form.is_valid():
            form.save()
            with open(app.log_file, 'wb') as out:
                out.write(b'# Cronjobs erstellen\n')
                proc = subprocess.Popen(
                    [settings.PYTHON_BIN, '-m', 'manage', 'install_cronjob', app.name],
                    stdout=out,
                    stderr=out,
                )
            return render(
                request,
                'app/wait_next.html',
                {
                    'step': 'Cronjobs installieren',
                    'pid': proc.pid,
                    'next': reverse('show-result', args=[app.id]),
                },
            )
    else:
        form = CronjobForm(app=app)

    return render(
        request,
        'app/cronjob_form.html',
        {
            'form': form,
            'app': app,
        },
    )

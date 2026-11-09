import subprocess  # nosec: B404

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from adminconsole.decorators import owner_of_app, owner_of_domain
from adminconsole.forms import DomainForm
from adminconsole.models import App, Domain
from adminconsole.views.generic import audit_log, client_address


@owner_of_app
def manage(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    if request.method == 'POST':
        form = DomainForm(request.POST, app=app)
        if form.is_valid():
            domain = form.save()
            audit_log.info(
                '%s adds domain %s to %s from %s',
                request.user,
                domain.name,
                app.name,
                client_address(request),
            )
            with open(app.log_file, 'wb') as out:
                out.write('# Domain hinzufügen\n'.encode())
                proc = subprocess.Popen(  # nosec: B603
                    [settings.PYTHON_BIN, '-m', 'manage', 'add_domain', domain.name],
                    stdout=out,
                    stderr=out,
                )
            return redirect(reverse('domain-add', args=[app.id, proc.pid]))
    else:
        form = DomainForm(app=app)

    return render(
        request,
        'app/domain_form.html',
        {'domains': app.domains.all(), 'form': form, 'app': app},
    )


@owner_of_app
@login_required
def add(request, app_id, pid):
    app = get_object_or_404(App, pk=app_id)
    render_dict = {
        'step': 'Domain hinzufügen',
        'pid': pid,
        'next': reverse('show-result', args=[app.id]),
    }
    return render(request, 'flow/wait_next.html', render_dict)


@owner_of_domain
@require_POST
def remove(request, domain_id):
    domain = get_object_or_404(Domain, pk=domain_id)
    app = domain.app
    audit_log.info(
        '%s removes domain %s from %s from %s',
        request.user,
        domain.name,
        app.name,
        client_address(request),
    )
    domain.delete()
    return redirect(reverse('domain-manage', args=[app.id]))


@owner_of_domain
@require_POST
def renew(request, domain_id):
    domain = get_object_or_404(Domain, pk=domain_id)
    audit_log.info(
        '%s renews domain %s of %s from %s',
        request.user,
        domain.name,
        domain.app.name,
        client_address(request),
    )
    with open(domain.app.log_file, 'wb') as out:
        out.write('# Domain erneuern\n'.encode())
        proc = subprocess.Popen(  # nosec: B603
            [settings.PYTHON_BIN, '-m', 'manage', 'add_domain', domain.name],
            stdout=out,
            stderr=out,
        )
    return redirect(reverse('domain-add', args=[domain.app.id, proc.pid]))

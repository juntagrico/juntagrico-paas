import subprocess  # nosec: B404

from django.conf import settings
from django.contrib import messages
from django.urls import reverse

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils.crypto import get_random_string

from adminconsole.decorators import owner_of_app
from adminconsole.models import App, GitHubKey
from adminconsole.util.git import (
    git_clone,
    github_auth_env,
    validate_clone_url,
    list_installation_repos,
)
from adminconsole.views.generic import confirm_post


def continue_setup(request, to='repo-source'):
    app_id = request.session.pop('github_install_app_id', None)
    if app_id:
        return redirect(to, app_id=app_id)
    return redirect('home')


@login_required
def github_callback(request):
    """Callback after the user installs the GitHub App.

    Captures the installation_id from the URL and stores it for the current user.
    A single-use state token in the session verifies that the callback originates
    from the legitimate installation flow initiated by this user, preventing
    attackers from crafting URLs with arbitrary installation_id values.
    """
    installation_id = request.GET.get('installation_id', '')
    setup_action = request.GET.get('setup_action', '')
    callback_state = request.GET.get('state', '')

    # Verify the single-use state token to prevent installation_id spoofing.
    # The state is passed through from the installation URL to the Setup URL callback.
    session_state = request.session.pop('github_install_state', None)
    if session_state is None or session_state != callback_state:
        messages.error(request, 'Ungültige GitHub-Antwort. Bitte versuche es erneut.')
        return continue_setup(request)

    # If admin approval is pending, inform the user
    if setup_action == 'request':
        messages.info(
            request,
            'Die GitHub App-Installation wartet auf Genehmigung durch einen '
            'Organisations-Administrator. Du kannst weitermachen, sobald sie genehmigt ist.',
        )
        return continue_setup(request)

    if not installation_id:
        messages.error(request, 'Ungültige GitHub-Antwort. Bitte versuche es erneut.')
        return continue_setup(request)

    # Store the installation_id for this user
    GitHubKey.objects.update_or_create(
        user=request.user,
        defaults={'installation_id': installation_id},
    )

    messages.success(request, 'GitHub App erfolgreich installiert.')

    # Redirect to repo selection if the user was creating an app
    return continue_setup(request, 'github-select')


@login_required
@owner_of_app
def repo_source(request, app_id):
    """Let the user choose between pasting a clone URL or connecting via GitHub."""
    app = get_object_or_404(App, pk=app_id)

    # If the app already has a clone URL, skip straight to cloning
    if app.git_clone_url:
        return redirect('ca-git-clone', app_id=app_id)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'github':
            # Store the app_id in the session so the callback can redirect to select_repo
            request.session['github_install_app_id'] = app_id
            # Generate a single-use state token to verify the callback originates
            # from this legitimate installation flow, preventing installation_id spoofing.
            # GitHub passes the state parameter through to the Setup URL callback.
            state = get_random_string(32)
            request.session['github_install_state'] = state
            # Redirect to the GitHub App installation page. After installation, GitHub
            # redirects to the Setup URL (configured in GitHub App settings) with
            # ?installation_id=XXX&state=YYY
            return redirect(
                f'https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new?state={state}'
            )
        if action == 'clone':
            clone_url = request.POST.get('clone_url', '').strip()
            error = validate_clone_url(clone_url)
            if error:
                messages.error(request, error)
                return render(
                    request,
                    'repo_source.html',
                    {'app': app, 'initial_url': clone_url},
                )
            # Clone URL validation succeeded — save the URL and proceed to clone
            # This path is for public repos; for private repos, use the GitHub App
            # installation flow (select_repo) which authenticates via installation tokens
            App.objects.filter(pk=app_id).update(git_clone_url=clone_url)
            return redirect('ca-git-clone', app_id=app_id)

    return render(request, 'repo_source.html', {'app': app})


@login_required
@owner_of_app
def select_repo(request, app_id):
    """List repos accessible via the current user's GitHub App installation."""
    app = get_object_or_404(App, pk=app_id)

    # If the app already has a clone URL, skip straight to cloning
    if app.git_clone_url:
        return redirect('ca-git-clone', app_id=app_id)

    # Look up the user's stored installation_id
    try:
        github_key = GitHubKey.objects.get(user=request.user)
        installation_id = int(github_key.installation_id)
    except (GitHubKey.DoesNotExist, ValueError):
        messages.info(
            request,
            'Du hast die GitHub App noch nicht installiert. '
            'Installiere sie zuerst, dann kannst du ein Repo auswählen.',
        )
        return redirect('repo-source', app_id=app_id)

    # Fetch repos for this user's installation only
    repos = list_installation_repos(installation_id) or []

    if request.method == 'POST':
        repo_full_name = request.POST.get('repo_full_name')
        if repo_full_name:
            # Save the clone URL and proceed
            clone_url = f'https://github.com/{repo_full_name}.git'
            App.objects.filter(pk=app_id).update(git_clone_url=clone_url)
            return redirect('ca-git-clone', app_id=app_id)

    return render(
        request,
        'select_repo.html',
        {'app': app, 'installation_id': installation_id, 'repos': repos},
    )


@owner_of_app
@confirm_post('Repo klonen', 'Repo klonen')
def clone_repo(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    if not app.git_clone_url:
        return redirect('repo-source', app_id=app_id)

    # Get an installation access token from the app's owner's installation
    key = app.get_installation_token()

    errors = []
    success = git_clone(app, key, errors)

    return render(
        request,
        'app/done_next.html',
        {
            'errors': '' if success else errors,
            'step': 'Repo Klonen',
            'next': reverse('ca-overwrite', args=[app_id]),
        },
    )


@owner_of_app
@confirm_post('Repo pushen', 'Code ins Repo pushen')
def git_push(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    directory = app.code_dir
    output = []
    proc = subprocess.run(  # nosec: B603, B607
        ['git', 'add', '.', '--all'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=directory,
    )
    output.append(str(proc.stdout))
    proc = subprocess.run(  # nosec: B603, B607
        ['git', 'commit', '-a', '-m', '"adminconsole"'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=directory,
    )
    output.append(str(proc.stdout))
    # Get an installation access token from the app's owner's installation
    token = app.get_installation_token()
    env = github_auth_env(token) if token else None
    proc = subprocess.run(  # nosec: B603, B607
        ['git', 'push'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=directory,
        env=env,
    )
    output.append(str(proc.stdout))

    errors = []
    if proc.returncode > 0:
        if token is None:
            output.insert(
                0,
                'Keine GitHub App-Installation gefunden. Für private Repos '
                'musst du zuerst die GitHub App installieren.',
            )
        errors.append(output)

    return render(
        request,
        'generic/done_next_submit.html',
        {
            'step': 'Cokkiecutter anwenden und repo pushen',
            'errors': errors,
            'next': reverse('ca-init-db', args=[app_id]),
        },
    )

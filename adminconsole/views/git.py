import json
import secrets
import subprocess
from urllib import request as r, parse

from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from github import Github, BadCredentialsException

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required

from adminconsole.decorators import owner_of_app
from adminconsole.models import GitHubKey, App
from adminconsole.util.create_app import make_dirs
from adminconsole.util.git import git_clone, github_auth_env
from adminconsole.views.generic import confirm_post


GITHUB_STATE_SESSION_KEY = 'github_oauth_state'


@login_required
def github_request(request):
    # random value that ties the callback to this request, so nobody can slip a foreign GitHub account to the user
    state = secrets.token_urlsafe(32)
    request.session[GITHUB_STATE_SESSION_KEY] = state
    params = parse.urlencode({
        'client_id': settings.GITHUB_CLIENT_ID,
        'scope': 'public_repo',
        'state': state,
    })
    return redirect(f'https://github.com/login/oauth/authorize?{params}')


def fetch_github_token(code):
    """exchanges the code from the callback for a token, returns None if GitHub does not grant one"""
    data = parse.urlencode({
        'code': code,
        'client_id': settings.GITHUB_CLIENT_ID,
        'client_secret': settings.GITHUB_CLIENT_SECRET,
    }).encode()
    req = r.Request(
        'https://github.com/login/oauth/access_token',
        data=data,
        headers={'Accept': 'application/json'},
    )
    try:
        with r.urlopen(req, timeout=10) as resp:
            payload = json.load(resp)
    except (OSError, ValueError):  # network errors, timeouts, invalid json
        return None
    return payload.get('access_token') if isinstance(payload, dict) else None


@login_required
def github_callback(request):
    expected_state = request.session.pop(GITHUB_STATE_SESSION_KEY, None)
    state = request.GET.get('state', '')
    if not expected_state or not secrets.compare_digest(
        state.encode(), expected_state.encode()
    ):
        messages.error(
            request,
            'Die Verbindung mit GitHub konnte nicht bestätigt werden. Bitte versuche es nochmals.',
        )
        return redirect('home')

    code = request.GET.get('code')
    key = fetch_github_token(code) if code else None
    if not key:
        # keep the existing token, it may still be valid
        messages.error(
            request, 'GitHub hat keinen Zugriff erteilt. Bitte versuche es nochmals.'
        )
        return redirect('home')

    GitHubKey.objects.update_or_create(user=request.user, defaults={'key': key})
    return redirect(request.session.pop('next', 'home'))


@owner_of_app
def select_repo(request, app_id):
    key_valid = False
    if hasattr(request.user, 'githubkey'):
        g = Github(request.user.githubkey.key)
        repos = g.get_user().get_repos()
        try:
            # check if key is still valid
            repos[0]
            key_valid = True
        except BadCredentialsException:
            pass
    if not key_valid:
        request.session['next'] = request.path
        return github_request(request)

    if request.method == 'POST':
        selected_repo = int(request.POST.get('repo'))
        App.objects.filter(pk=app_id).update(
            git_clone_url=g.get_repo(selected_repo).clone_url
        )
        return redirect('ca-git-clone', app_id=app_id)

    return render(
        request,
        'repos.html',
        {
            'repos': repos,
        },
    )


@owner_of_app
@confirm_post('Repo klonen', 'Repo klonen')
def clone_repo(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    if not app.git_clone_url:
        return redirect('github-select', app_id=app_id)

    key = None
    if hasattr(request.user, 'githubkey'):
        key = request.user.githubkey.key

    errors = []
    success = make_dirs(app.dir, errors)
    if success:
        success &= git_clone(app, key, errors)

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
    proc = subprocess.run(
        ['git', 'add', '.', '--all'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=directory,
    )
    output.append(str(proc.stdout))
    proc = subprocess.run(
        ['git', 'commit', '-a', '-m', '"adminconsole"'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=directory,
    )
    output.append(str(proc.stdout))
    # the token is only passed to this command, the repository has no credentials stored
    env = (
        github_auth_env(request.user.githubkey.key)
        if hasattr(request.user, 'githubkey')
        else None
    )
    proc = subprocess.run(
        ['git', 'push'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=directory,
        env=env,
    )
    output.append(str(proc.stdout))

    errors = []
    if proc.returncode > 0:
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

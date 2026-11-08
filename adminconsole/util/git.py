import base64
import os
import re
import time
import subprocess  # nosec: B404
from urllib.parse import urlsplit, urlunsplit

import jwt

from django.conf import settings
from adminconsole.config import test_localhost


def _create_github_jwt():
    """Create a JSON Web Token for authenticating as a GitHub App."""
    now = int(time.time())
    payload = {
        'iat': now - 60,  # 1 minute ago (clock skew tolerance)
        'exp': now + 600,  # 10 minutes from now (GitHub max)
        'iss': settings.GITHUB_APP_ID,
    }
    return jwt.encode(payload, settings.GITHUB_APP_PRIVATE_KEY, algorithm='RS256')


def _github_app_request(method, url, **kwargs):
    """Make an authenticated request to the GitHub API as a GitHub App."""
    import urllib.request as ur  # defer import

    jwt_token = _create_github_jwt()
    req = ur.Request(
        url,
        method=method,
        headers={
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {jwt_token}',
            'X-GitHub-Api-Version': '2022-11-28',
        },
        **kwargs,
    )
    with ur.urlopen(req, timeout=10) as resp:
        import json

        return json.load(resp)


def get_installation_access_token(installation_id: int) -> str | None:
    """Generate an installation access token for a GitHub App installation.

    Returns the access token string, or None on failure.
    The token expires after 1 hour.
    """
    try:
        data = _github_app_request(
            'POST',
            f'https://api.github.com/app/installations/{installation_id}/access_tokens',
            data=b'{}',
        )
        return data.get('token')
    except (OSError, ValueError):
        return None


def list_installation_repos(installation_id: int) -> list[dict] | None:
    """List repositories accessible to a specific GitHub App installation.

    Returns a list of repo dicts (each with 'owner', 'name', 'full_name', etc.), or None on failure.
    """
    try:
        token = get_installation_access_token(installation_id)
        if token is None:
            return None
        import urllib.request as ur

        req = ur.Request(
            'https://api.github.com/installation/repositories',
            method='GET',
            headers={
                'Accept': 'application/vnd.github+json',
                'Authorization': f'Bearer {token}',
                'X-GitHub-Api-Version': '2022-11-28',
            },
        )
        with ur.urlopen(req, timeout=10) as resp:
            import json

            return json.load(resp).get('repositories', [])
    except (OSError, ValueError):
        return None


def github_auth_env(key):
    """
    Environment for a single git command that authenticates with a GitHub token.
    The token is passed as HTTP header via environment variables (requires git >= 2.31), so it is neither stored
    in the repository (e.g. in the remote url) nor visible in the process list. The header is only sent to
    https://github.com/.
    Credential helpers are disabled, so git neither sends other stored credentials nor erases them if the token
    is rejected.
    """
    credentials = base64.b64encode(f'{key}:x-oauth-basic'.encode()).decode()
    return {
        **os.environ,
        'GIT_CONFIG_COUNT': '2',
        'GIT_CONFIG_KEY_0': 'http.https://github.com/.extraHeader',
        'GIT_CONFIG_VALUE_0': f'Authorization: Basic {credentials}',
        'GIT_CONFIG_KEY_1': 'credential.helper',
        'GIT_CONFIG_VALUE_1': '',  # an empty value resets the list of credential helpers
        'GIT_TERMINAL_PROMPT': '0',
    }


def remove_credentials(url):
    """returns the url without user name and password"""
    parts = urlsplit(url)
    if '@' not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rpartition('@')[2]))


def validate_clone_url(url):
    """Check whether a git clone URL points to an accessible repository.

    Uses `git ls-remote` which only lists refs without cloning anything.
    Returns None on success, or an error message string on failure.
    """
    if not url or not url.strip():
        return 'Bitte gib eine gültige Clone-URL ein.'
    if not test_localhost():
        proc = subprocess.run(  # nosec: B603, B607
            ['git', 'ls-remote', '--exit-code', url],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        if proc.returncode != 0:
            return (
                'Das Repo konnte nicht erreicht werden. '
                'Bitte überprüfe die URL und versuche es erneut.'
            )
    return None


def git_clone(app, key=None, output=None):
    if not test_localhost():
        branch = ['-b', app.git_branch] if app.git_branch else []
        proc = subprocess.run(  # nosec: B603, B607
            ['git', 'clone', *branch, '--depth=1', app.git_clone_url, app.code_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=github_auth_env(key) if key else None,
        )
        if output is not None:
            output.append(proc.stdout.decode())
        return proc.returncode == 0
    return True


def run_git(args, cdir, **kwargs):
    return subprocess.run(['git', *args], cwd=cdir, **kwargs)  # nosec: B603, B607


def git_pull(app):
    cdir = app.code_dir
    # Try to get an installation token for private repo access
    token = app.get_installation_token()
    env = github_auth_env(token) if token else None

    if app.git_branch:
        fetch = run_git(
            ['fetch', '--no-tags', '--depth=1', app.git_clone_url, app.git_branch],
            cdir,
            stderr=subprocess.STDOUT,
            env=env,
        )
        if fetch.returncode != 0:
            return fetch.returncode

        current = run_git(
            ['rev-parse', 'HEAD'], cdir, capture_output=True, text=True
        ).stdout.strip()
        target = run_git(
            ['rev-parse', 'FETCH_HEAD'], cdir, capture_output=True, text=True
        ).stdout.strip()

        if current == target:
            return 0

        reset = run_git(
            ['reset', '--hard', 'FETCH_HEAD'], cdir, stderr=subprocess.STDOUT
        )
        return reset.returncode

    proc1 = subprocess.run(  # nosec: B603, B607
        ['git', 'fetch', '--depth=1'], stderr=subprocess.STDOUT, cwd=cdir, env=env
    )
    if proc1.returncode != 0:
        return proc1.returncode
    proc2 = subprocess.run(  # nosec: B603, B607
        ['git', 'reset', '--hard', '@{u}'], stderr=subprocess.STDOUT, cwd=cdir
    )
    return proc2.returncode


def validate_branch(app, branch):
    """Validate a branch name: sanitize, check format, and verify it exists remotely (v3+).
    Returns None on success, or an error message string on failure.
    """
    branch = re.sub('[?*[@#$;&~^: ]', '', branch)

    proc = subprocess.run(  # nosec: B603, B607
        ['git', 'check-ref-format', '--branch', branch],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        return proc.stdout.decode(errors='replace')

    if app.version >= 3:
        # Try to get an installation token for private repo access
        token = app.get_installation_token()
        env = github_auth_env(token) if token else None

        proc = subprocess.run(  # nosec: B603, B607
            [
                'git',
                'ls-remote',
                '--exit-code',
                '--heads',
                app.git_clone_url,
                f'refs/heads/{branch}',
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        if proc.returncode != 0:
            return 'Branch nicht gefunden'
    return None


def git_switch(app, branch):
    cdir = app.code_dir
    error = validate_branch(app, branch)
    if error:
        return error

    if app.version >= 3:
        app.set_branch(branch)  # save current branch in db
        return ''

    proc = subprocess.run(  # nosec: B603, B607
        ['git', 'remote', 'set-branches', 'origin', branch],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cdir,
    )
    if proc.returncode != 0:
        return 'git remote: ' + proc.stdout.decode()

    proc = subprocess.run(  # nosec: B603, B607
        ['git', 'fetch', '--depth=1', 'origin', branch],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cdir,
    )
    if proc.returncode != 0:
        error = 'git fetch: ' + proc.stdout.decode()
        # try to restore old branch
        old_branch = git_current_branch(app)
        if old_branch != branch:
            subprocess.run(  # nosec: B603, B607
                ['git', 'remote', 'set-branches', 'origin', old_branch],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cdir,
            )
        return error

    proc = subprocess.run(  # nosec: B603, B607
        ['git', 'checkout', '-B', branch],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cdir,
    )
    if proc.returncode != 0:
        return 'git checkout:' + proc.stdout.decode()

    proc = subprocess.run(  # nosec: B603, B607
        ['git', 'branch', '-u', 'origin/' + branch, branch],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cdir,
    )
    if proc.returncode != 0:
        return 'git branch: ' + proc.stdout.decode()

    app.set_branch(branch)  # save current branch in db
    return ''


def git_status(app, errors=None):
    cdir = app.code_dir
    if not cdir.is_dir():
        if errors is not None:
            errors.append('folder not found: ' + str(cdir))
        return False
    proc = subprocess.run(  # nosec: B603, B607
        ['git', 'status'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir
    )
    if errors is not None:
        errors.append(proc.stdout.decode())
    return proc.returncode == 0


def git_current_branch(app):
    if app.version >= 3:
        return app.git_branch or 'main'
    proc = subprocess.Popen(  # nosec: B603, B607
        ['git', 'branch', '--show-current'], stdout=subprocess.PIPE, cwd=app.code_dir
    )
    return proc.stdout.read().decode().strip()

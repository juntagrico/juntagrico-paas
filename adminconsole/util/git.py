import base64
import os
import re
import subprocess
from urllib.parse import urlsplit, urlunsplit

from adminconsole.config import Config


def github_auth_env(key):
    """
    Environment for a single git command that authenticates with the GitHub token.
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
    """ returns the url without user name and password """
    parts = urlsplit(url)
    if '@' not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rpartition('@')[2]))


def git_clone(app, key=None, output=None):
    if not Config.test_localhost():
        branch = ['-b', app.git_branch] if app.git_branch else []
        proc = subprocess.run(['git', 'clone', *branch, '--depth=1', app.git_clone_url, 'code'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=app.dir,
                              env=github_auth_env(key) if key else None)
        if output is not None:
            output.append(proc.stdout.decode())
        return proc.returncode == 0
    return True


def run_git(args, cdir, **kwargs):
    return subprocess.run(
        ["git", *args], cwd=cdir, **kwargs
    )


def git_pull(app):
    cdir = app.code_dir
    if app.git_branch:
        fetch = run_git(
            ['fetch', '--no-tags', '--depth=1', app.git_clone_url, app.git_branch],
            cdir,
            stderr=subprocess.STDOUT,
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

        reset = run_git(['reset', '--hard', 'FETCH_HEAD'], cdir, stderr=subprocess.STDOUT)
        return reset.returncode

    proc1 = subprocess.run(['git', 'fetch', '--depth=1'], stderr=subprocess.STDOUT, cwd=cdir)
    if proc1.returncode != 0:
        return proc1.returncode
    proc2 = subprocess.run(['git', 'reset', '--hard', '@{u}'], stderr=subprocess.STDOUT, cwd=cdir)
    return proc2.returncode


def validate_branch(app, branch):
    """Validate a branch name: sanitize, check format, and verify it exists remotely (v3+).
    Returns None on success, or an error message string on failure.
    """
    branch = re.sub('[?*[@#$;&~^: ]', '', branch)

    proc = subprocess.run(['git', 'check-ref-format', '--branch', branch],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        return proc.stdout.decode(errors='replace')

    if app.version >= 3:
        proc = subprocess.run(
            ['git', 'ls-remote', '--exit-code', '--heads', app.git_clone_url, f'refs/heads/{branch}'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
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

    proc = subprocess.run(['git', 'remote', 'set-branches', 'origin', branch],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
    if proc.returncode != 0:
        return 'git remote: ' + proc.stdout.decode()

    proc = subprocess.run(['git', 'fetch', '--depth=1', 'origin', branch],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
    if proc.returncode != 0:
        error = 'git fetch: ' + proc.stdout.decode()
        # try to restore old branch
        old_branch = git_current_branch(app)
        if old_branch != branch:
            subprocess.run(['git', 'remote', 'set-branches', 'origin', old_branch],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
        return error

    proc = subprocess.run(['git', 'checkout', '-B', branch],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
    if proc.returncode != 0:
        return 'git checkout:' + proc.stdout.decode()

    proc = subprocess.run(['git', 'branch', '-u', 'origin/' + branch, branch],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
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
    proc = subprocess.run(['git', 'status'],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
    if errors is not None:
        errors.append(proc.stdout.decode())
    return proc.returncode == 0


def git_current_branch(app):
    if app.version >= 3:
        return app.git_branch or 'main'
    proc = subprocess.Popen(['git', 'branch', '--show-current'], stdout=subprocess.PIPE, cwd=app.code_dir)
    return proc.stdout.read().decode().strip()

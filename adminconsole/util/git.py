import re
import subprocess

from adminconsole.config import Config


def git_clone(app, key=None, output=None):
    if not Config.test_localhost():
        clone_url, _, branch = app.git_clone_url.partition('@')
        if key:
            protocol, clone_path = clone_url.split('://')
            clone_url = protocol + '://' + key + ':x-oauth-basic@' + clone_path
        if branch:
            branch = ['-b', branch]
        proc = subprocess.run(['git', 'clone', *branch, '--depth=1', clone_url, 'code'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=app.dir)
        if output is not None:
            output.append(proc.stdout.decode())
        return proc.returncode == 0
    return True


def git_pull(app):
    cdir = app.code_dir
    proc1 = subprocess.run(['git', 'fetch', '--depth=1'], stderr=subprocess.STDOUT, cwd=cdir)
    if proc1.returncode != 0:
        return proc1.returncode
    proc2 = subprocess.run(['git', 'reset', '--hard', '@{u}'], stderr=subprocess.STDOUT, cwd=cdir)
    return proc2.returncode


def git_switch(app, branch):
    cdir = app.code_dir
    branch = re.sub('[?*[@#$;&~^: ]', '', branch)

    proc = subprocess.run(['git', 'check-ref-format', '--branch',  branch],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
    if proc.returncode != 0:
        return proc.stdout.decode()

    proc = subprocess.run(['git', 'remote', 'set-branches', 'origin', branch],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
    if proc.returncode != 0:
        return 'git remote: ' + proc.stdout.decode()

    proc = subprocess.run(['git', 'fetch', '--depth=1', 'origin', branch],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
    if proc.returncode != 0:
        return 'git fetch: ' + proc.stdout.decode()

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
    proc = subprocess.Popen(['git', 'branch', '--show-current'], stdout=subprocess.PIPE, cwd=app.code_dir)
    return proc.stdout.read().decode().strip()

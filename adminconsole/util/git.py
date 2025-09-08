import subprocess

from adminconsole.config import Config


def git_clone(key, app, output=None):
    if not Config.test_localhost():
        url = 'https://' + key + ':x-oauth-basic@' + app.git_clone_url[8:]
        proc = subprocess.run(['git', 'clone', '--depth=1', url, 'code'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=app.dir)
        if output is not None:
            output.append(proc.stdout.decode())
        return proc.returncode == 0
    return True


def git_pull(app):
    cdir = app.dir / 'code'
    proc1 = subprocess.run(['git', 'fetch', '--depth=1'], stderr=subprocess.STDOUT, cwd=cdir)
    proc2 = subprocess.run(['git', 'reset', '--hard', '@{u}'], stderr=subprocess.STDOUT, cwd=cdir)
    return proc1.returncode + proc2.returncode


def git_status(app, errors=None):
    cdir = app.dir / 'code'
    if not cdir.is_dir():
        if errors is not None:
            errors.append('folder not found: ' + str(cdir))
        return False
    proc = subprocess.run(['git', 'status'],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cdir)
    if errors is not None:
        errors.append(proc.stdout.decode())
    return proc.returncode == 0

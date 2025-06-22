import subprocess

from adminconsole.config import Config
from adminconsole.models import App


def find_port():
    ports = App.objects.all().values_list('port', flat=True)
    port = 8010
    while port in ports:
        port += 1
    return port


def make_dirs(directory, output=None):
    result = True
    proc = subprocess.run(['mkdir', directory], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    result &= proc.returncode != 0
    if output:
        output.append(str(proc.stdout))

    proc = subprocess.run(['mkdir', 'static'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=directory)
    result &= proc.returncode != 0
    if output:
        output.append(str(proc.stdout))

    proc = subprocess.run(['mkdir', 'media'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=directory)
    result &= proc.returncode != 0
    if output:
        output.append(str(proc.stdout))
    return result


def git_clone(user, app, output=None):
    if not Config.test_localhost():
        key = user.githubkey.key
        url = 'https://' + key + ':x-oauth-basic@' + app.git_clone_url[8:]
        proc = subprocess.run(['git', 'clone', url, 'code'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=app.dir)
        if output:
            output.append(str(proc.stdout))
        return proc.returncode != 0
    return True

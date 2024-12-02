from datetime import datetime
from time import sleep

import docker
import subprocess

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):

        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        cdir = '/var/django/projects/'+name+'/code'

        client = docker.from_env()

        container = client.containers.get(name)

        print('Fetch latest code', flush=True)
        proc1 = subprocess.run(['git', 'fetch'], stderr=subprocess.STDOUT, cwd=cdir)
        proc2 = subprocess.run(['git', 'reset', '--hard', '@{u}'], stderr=subprocess.STDOUT, cwd=cdir)
        print('Return ', proc1.returncode + proc2.returncode, flush=True)

        print('Install Requirements', flush=True)
        cmd = 'pip install --upgrade -r requirements.txt'
        result = container.exec_run(cmd)
        print(result[1])
        print('Return ', result[0], flush=True)

        if result[0] == 0:  # only continue if pip install succeeded
            print('Commit to Docker Container', flush=True)
            result = container.commit(repository=name, tag='latest')
            print(result)
            print('Return 0', flush=True)

            print('Restart Docker Container', flush=True)
            restart(container)

            print('Django Migrate', flush=True)
            cmd = ['python', '-m', 'manage', 'migrate']
            result = container.exec_run(cmd)
            print(result[1])
            print('Return ', result[0], flush=True)

            print('Django Collectstatic', flush=True)
            cmd = ['python', '-m', 'manage', 'collectstatic', '--noinput', '-c']
            result = container.exec_run(cmd)
            print(result[1])
            print('Return ', result[0], flush=True)

            print('Restart Docker Container again', flush=True)
            restart(container)
        else:
            print('ERROR!')
            print('pip install failed! Fix your requirements.txt and redeploy. '
                  'Do not restart the instance.', flush=True)


def restart(container, timeout=20):
    """ restarts docker container and waits until it is running, then prints the log of the restart
    :param container: a docker container
    :param timeout: timeout in seconds
    """
    now = datetime.now()
    container.restart()
    sleep(1)
    container.reload()
    elapsed_time = 0
    interval = 1
    while container.status != 'running' and elapsed_time < timeout:
        sleep(interval)
        elapsed_time += interval
        container.reload()
        continue
    print(container.logs(since=now))
    print('Return 0', flush=True)

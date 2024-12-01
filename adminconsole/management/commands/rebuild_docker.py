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

        print('Fetch latest code')
        subprocess.run(['git', 'fetch'], stderr=subprocess.STDOUT, cwd=cdir)
        subprocess.run(['git', 'reset', '--hard', '@{u}'], stderr=subprocess.STDOUT, cwd=cdir)

        print('Install Requirements')
        cmd = 'pip install --upgrade -r requirements.txt'
        result = container.exec_run(cmd)
        print(result[1])

        if result[0] == 0:  # only continue if pip install succeeded
            print('Commit to Docker Container')
            result = container.commit(repository=name, tag='latest')
            print(result)

            print('Restart Docker Container')
            restart(container)

            print('Django Migrate')
            cmd = ['python', '-m', 'manage', 'migrate']
            result = container.exec_run(cmd)
            print(result[1])

            print('Django Collectstatic')
            cmd = ['python', '-m', 'manage', 'collectstatic', '--noinput', '-c']
            result = container.exec_run(cmd)
            print(result[1])

            print('Restart Docker Container again')
            restart(container)
        else:
            print('ERROR!')
            print('pip install failed! Fix your requirements.txt and redeploy. Do not restart the instance.')


def restart(container, timeout=20):
    """ restarts docker container and waits until it is running, then prints the log of the restart
    :param container: a docker container
    :param timeout: timeout in seconds
    """
    now = datetime.now()
    container.restart()
    elapsed_time = 0
    interval = 1
    while container.status != 'running' and elapsed_time < timeout:
        sleep(interval)
        elapsed_time += interval
        container.reload()
        continue
    print(container.logs(since=now))

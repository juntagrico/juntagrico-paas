from datetime import datetime
from time import sleep

import docker
import subprocess

from django.core.management.base import BaseCommand

from adminconsole.util.commands import log_after


class Command(BaseCommand):
    def add_arguments(self, parser):

        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        cdir = '/var/django/projects/'+name+'/code'

        client = docker.from_env()

        container = client.containers.get(name)

        print('# Git Pull', flush=True)
        proc1 = subprocess.run(['git', 'fetch'], stderr=subprocess.STDOUT, cwd=cdir)
        proc2 = subprocess.run(['git', 'reset', '--hard', '@{u}'], stderr=subprocess.STDOUT, cwd=cdir)
        print('Return ', proc1.returncode + proc2.returncode, flush=True)

        print('# Install Requirements', flush=True)
        cmd = 'pip install --upgrade -r requirements.txt'
        result = container.exec_run(cmd)
        print(result[1])
        print('Return ', result[0], flush=True)

        if result[0] == 0:  # only continue if pip install succeeded
            print('# Docker Commit', flush=True)
            result = container.commit(repository=name, tag='latest')
            print(result)
            print('Return 0', flush=True)

            print('# Docker Restart', flush=True)
            start = datetime.now()
            container.restart()
            print(log_after(container, since=start))
            print('Return 0', flush=True)

            print('# Django Migrate', flush=True)
            cmd = ['python', '-m', 'manage', 'migrate']
            result = container.exec_run(cmd)
            print(result[1])
            print('Return ', result[0], flush=True)

            print('# Django Collectstatic', flush=True)
            cmd = ['python', '-m', 'manage', 'collectstatic', '--noinput', '-c']
            result = container.exec_run(cmd)
            print(result[1])
            print('Return ', result[0], flush=True)

            print('# Docker Restart 2', flush=True)
            start = datetime.now()
            container.restart()
            print(log_after(container, since=start))
            print('Return 0', flush=True)
        else:
            print('ERROR!')
            print('pip install failed! Fix your requirements.txt and redeploy. '
                  'Do not restart the instance.', flush=True)

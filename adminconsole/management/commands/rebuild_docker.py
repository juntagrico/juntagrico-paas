from datetime import datetime

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
        subprocess.run(['git', 'fetch'], cwd=cdir)
        subprocess.run(['git', 'reset', '--hard', '@{u}'], cwd=cdir)

        print('Install Requirements')
        cmd = 'pip install --upgrade -r requirements.txt'
        result = container.exec_run(cmd)
        print(result[1])

        if result[0] == 0:  # only continue if pip install succeeded
            print('Commit to Docker Container')
            result = container.commit(repository=name, tag='latest')
            print(result)

            print('Restart Docker Container')
            now = datetime.now()
            container.restart()
            print(container.logs(since=now))

            print('Django Migrate')
            cmd = ['python', '-m', 'manage', 'migrate']
            result = container.exec_run(cmd)
            print(result[1])

            print('Django Collectstatic')
            cmd = ['python', '-m', 'manage', 'collectstatic', '--noinput', '-c']
            result = container.exec_run(cmd)
            print(result[1])

            print('Restart Docker Container again')
            now = datetime.now()
            container.restart()
            print(container.logs(since=now))
        else:
            print('ERROR!')
            print('pip install failed! Fix your requirements.txt and redeploy. Do not restart the instance.')

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

        subprocess.run(['git', 'fetch'], cwd=cdir)
        subprocess.run(['git', 'reset', '--hard', '@{u}'], cwd=cdir)

        cmd = 'pip install --upgrade -r requirements.txt'
        result = container.exec_run(cmd)
        print(result[1])

        if result[0] == 0:  # only continue if pip install succeeded
            result = container.commit(repository=name, tag='latest')
            print(result)

            container.restart()
            print(container.logs())

            cmd = ['python', '-m', 'manage', 'migrate']
            result = container.exec_run(cmd)
            print(result[1])
            cmd = ['python', '-m', 'manage', 'collectstatic', '--noinput', '-c']
            result = container.exec_run(cmd)
            print(result[1])

            container.restart()
            print(container.logs())
        else:
            print('pip install failed! Fix your requirements.txt and redeploy. Do not restart the instance.')


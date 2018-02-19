import docker
import subprocess

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):

        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        dir = '/var/django/projects/'+name
        cdir = '/var/django/projects/'+name+'/code'

        with open(dir+'/build/'+name+'.env') as f:
            env = f.readlines()
        env = [x.strip() for x in env] 

        client = docker.from_env()

        container = client.containers.get(name)

        proc = subprocess.run(['git', 'pull'], stdout = subprocess.PIPE, cwd=cdir)
        print(str(proc.stdout))

        cmd = ['pip', 'install', '--upgrade', '-r', 'requirements.txt']
        result = container.exec_run(cmd)
        print(result[1])

        container.commit(repository=name,
                           tag='latest')

        container.restart()
        result = client.images.build(path=dir+'/build/',
                            tag=name+':latest')

        cmd = ['python', '-m', 'manage', 'migrate']
        result = container.exec_run(cmd)
        print(result[1]))
        cmd = ['python', '-m', 'manage', 'collectstatic', '--noinput', '-c']
        result = container.exec_run(cmd)
        print(result[1])

